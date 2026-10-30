"""Self-contained Web Push policy tests (no devices or network required)."""
import asyncio

from app.push_notify import notify_event, valid_push_endpoint


def test_known_push_endpoints():
    assert valid_push_endpoint("https://fcm.googleapis.com/fcm/send/test")
    assert valid_push_endpoint("https://web.push.apple.com/test")
    assert valid_push_endpoint("https://updates.push.services.mozilla.com/push/v1/test")


def test_unknown_hosts_blocked():
    for value in ["http://web.push.apple.com/test", "https://127.0.0.1/test",
                  "https://evil.invalid/test", "https://web.push.apple.com.evil.invalid/test"]:
        assert not valid_push_endpoint(value)


def test_only_critical_events_notify(monkeypatch):
    called = []

    async def fake_send(title, body, *, url, tag):
        called.append((title, body, url, tag))
        return {"sent": 1, "total": 1}

    monkeypatch.setattr("app.push_notify.send_push_all", fake_send)
    async def case():
        await notify_event({"id": 8, "type": "motion", "message": "Motion"})
        await notify_event({"id": 9, "type": "fall_detected", "message": "Ngã"})
        await notify_event({"id": 10, "type": "gas_alarm", "message": "Gas"})
        await notify_event({"id": 11, "type": "device_offline", "message": "Offline"})

    asyncio.run(case())
    assert len(called) == 3
    assert all(u == "/events" for _, _, u, _ in called)
