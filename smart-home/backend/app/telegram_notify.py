"""Gửi cảnh báo Telegram qua gateway của nhóm (cùng giao thức với FallGuard).

POST {URL}/gateway/v1/notify, header X-Gateway-Key, JSON {title, message, level, event_id}.
Gateway gửi tới mọi người đã /start với bot.
"""
import asyncio
import json
import logging
import urllib.error
import urllib.request
import uuid

from .config import settings

log = logging.getLogger("telegram")

GATEWAY_PATH = "/gateway/v1/notify"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Không bao giờ gửi khóa sang địa chỉ khác khi bị chuyển hướng."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _post(title: str, message: str, level: str) -> None:
    url = settings.telegram_gateway_url.rstrip("/") + GATEWAY_PATH
    payload = {
        "title": title.strip()[:120],
        "message": message.strip()[:3500],
        "level": level,                                   # info | warning | critical
        "event_id": "smarthome-" + uuid.uuid4().hex,      # gateway dùng để chống gửi trùng
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={
            "X-Gateway-Key": settings.telegram_gateway_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.build_opener(_NoRedirect()).open(req, timeout=20) as resp:
            result = json.loads(resp.read(16_384))
    except urllib.error.HTTPError as exc:
        # 401: sai khóa | 403: bị chặn (Vercel) | 404: sai địa chỉ | 422: sai định dạng
        log.warning("Gateway báo HTTP %s", exc.code)
        return
    except (OSError, ValueError):
        log.warning("Không kết nối được gateway hoặc phản hồi không hợp lệ")
        return

    sent = result.get("sent", 0)
    if result.get("ok") is True and isinstance(sent, int) and sent >= 1:
        log.info("Đã gửi cảnh báo Telegram tới %s người", sent)
    else:
        log.warning("Gateway chưa gửi tới ai (cần /start với bot): %s", result)


async def send_telegram(message: str, title: str = "SMART HOME", level: str = "info") -> None:
    """Không làm gì nếu chưa cấu hình; chạy ở luồng riêng nên không chặn backend."""
    if not (settings.telegram_gateway_url and settings.telegram_gateway_key):
        return
    await asyncio.to_thread(_post, title, message, level)