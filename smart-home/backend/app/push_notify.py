"""Deliver Web Push alerts; failures never prevent persisting an incident."""
import asyncio
import json
import logging
from urllib.parse import urlsplit

from pywebpush import WebPushException, webpush
from sqlalchemy import select

from .config import settings
from .database import SessionLocal
from .models import PushSubscription

log = logging.getLogger(__name__)

# Limit outbound push requests to known browser push services (SSRF protection).
ALLOWED_PUSH_HOSTS = (
    "fcm.googleapis.com", ".push.apple.com", ".push.services.mozilla.com",
    "push.services.mozilla.com", ".notify.windows.com", ".push.microsoft.com",
)


def valid_push_endpoint(value: str) -> bool:
    if not isinstance(value, str) or len(value) > 4096:
        return False
    try:
        url = urlsplit(value)
        host = (url.hostname or "").lower()
        return (url.scheme == "https" and url.port in (None, 443)
                and not url.username and not url.password
                and bool(url.path) and not url.fragment
                and any(host == suffix or (suffix.startswith(".") and host.endswith(suffix))
                        for suffix in ALLOWED_PUSH_HOSTS))
    except ValueError:
        return False


def enabled() -> bool:
    return bool(settings.vapid_public_key and settings.vapid_private_key
                and settings.vapid_subject.startswith(("mailto:", "https://")))


def _send_one(sub: dict, payload: str) -> tuple[str, bool, int | None]:
    endpoint = sub["endpoint"]
    try:
        webpush(
            subscription_info=sub,
            data=payload,
            vapid_private_key=settings.vapid_private_key,
            vapid_claims={"sub": settings.vapid_subject},
            ttl=3600,
            timeout=8,
        )
        return (endpoint, True, None)
    except WebPushException as exc:
        code = exc.status_code
        log.warning("Push delivery failed (HTTP %s)", code)
        return (endpoint, False, code)
    except Exception:
        log.exception("Push delivery failed")
        return (endpoint, False, None)


async def send_push_all(title: str, body: str, *, url: str = "/events", tag: str = "smart-home") -> dict:
    """Fan out to registered browsers after the event transaction has committed."""
    if not enabled():
        return {"configured": False, "sent": 0, "total": 0}
    with SessionLocal() as db:
        subscriptions = [
            {"endpoint": s.endpoint, "keys": {"p256dh": s.p256dh, "auth": s.auth}}
            for s in db.scalars(select(PushSubscription)).all()
        ]
    body_json = json.dumps({"title": title[:120], "body": body[:500],
                            "url": url if url.startswith("/") and not url.startswith("//") else "/events",
                            "tag": tag[:100]}, ensure_ascii=False)
    semaphore = asyncio.Semaphore(8)

    async def one(subscription):
        async with semaphore:
            return await asyncio.to_thread(_send_one, subscription, body_json)

    results = await asyncio.gather(*(one(s) for s in subscriptions))
    dead = [endpoint for endpoint, _, code in results if code in (404, 410)]
    if dead:
        with SessionLocal() as db:
            db.query(PushSubscription).filter(PushSubscription.endpoint.in_(dead)).delete(synchronize_session=False)
            db.commit()
    return {"configured": True, "total": len(results),
            "sent": sum(1 for _, ok, _ in results if ok)}


async def notify_event(event: dict):
    """Map known events to push; ignore benign automation and telemetry."""
    if event["type"] == "fall_detected":
        title = "SMART HOME - PHÁT HIỆN NGÃ"
    elif event["type"] == "gas_alarm":
        title = "SMART HOME - CẢNH BÁO GAS/KHÓI"
    elif event["type"] == "device_offline":
        title = "SMART HOME - MẤT KẾT NỐI"
    else:
        return
    try:
        await send_push_all(title, event["message"], url="/events", tag=f"event-{event['id']}")
    except Exception:
        log.exception("Push failed for event %s", event["id"])
