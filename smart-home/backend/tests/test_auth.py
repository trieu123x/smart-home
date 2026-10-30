import base64

import pytest
from starlette.websockets import WebSocketDisconnect

from app import models, security
from app.config import settings
from conftest import DEVICE_KEY

PASSWORD = "correct horse battery"


@pytest.fixture
def locked(monkeypatch):
    monkeypatch.setattr(settings, "dashboard_password", PASSWORD)


def _login(client, password=PASSWORD):
    return client.post("/api/auth/login", json={"password": password})


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_login_right_wrong_and_rate_limited(client, locked):
    ok = _login(client)
    assert ok.status_code == 200
    body = ok.json()
    assert body["token"] and body["expires_at"].endswith("Z")

    for _ in range(5):
        assert _login(client, "wrong").status_code == 401
    sixth = _login(client, "wrong")
    assert sixth.status_code == 429
    # Rate-limited even with the right password until the window passes
    assert _login(client).status_code == 429


def test_rate_limit_is_per_client_ip(client, locked):
    for _ in range(5):
        assert _login(client, "wrong").status_code == 401
    # Header is ignored for a non-loopback peer ("testclient"), so it cannot dodge the limit
    spoofed = client.post(
        "/api/auth/login", json={"password": "wrong"}, headers={"CF-Connecting-IP": "1.2.3.4"}
    )
    assert spoofed.status_code == 429


def test_dashboard_endpoint_needs_token(client, locked):
    assert client.get("/api/devices").status_code == 401
    assert client.get("/api/live").status_code == 401
    assert client.get("/api/analytics/lake").status_code == 401
    assert client.get("/api/auth/me").status_code == 401

    token = _login(client).json()["token"]
    assert client.get("/api/devices", headers=_bearer(token)).status_code == 200
    assert client.get("/api/auth/me", headers=_bearer(token)).json() == {"ok": True}


def test_expired_token_is_rejected(client, locked, monkeypatch):
    monkeypatch.setattr(settings, "auth_token_hours", -1)
    token, _ = security.create_token()
    assert client.get("/api/devices", headers=_bearer(token)).status_code == 401


def test_tampered_token_is_rejected(client, locked):
    token = _login(client).json()["token"]
    payload, signature = token.split(".")
    expiry = int(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    forged = base64.urlsafe_b64encode(str(expiry + 3600).encode()).rstrip(b"=").decode()

    for bad in (f"{forged}.{signature}", f"{payload}.{signature[:-2]}", "garbage", ""):
        assert client.get("/api/devices", headers=_bearer(bad)).status_code == 401


def test_password_change_invalidates_tokens(client, locked, monkeypatch):
    token = _login(client).json()["token"]
    monkeypatch.setattr(settings, "dashboard_password", "a different password")
    assert client.get("/api/devices", headers=_bearer(token)).status_code == 401


def test_ingest_still_works_with_device_key_only(client, locked):
    response = client.post(
        "/api/ingest/telemetry",
        headers=DEVICE_KEY,
        json={"device_code": "esp32-test", "metrics": {"temperature": 30.0}},
    )
    assert response.status_code == 202
    assert client.post(
        "/api/ingest/telemetry", json={"device_code": "x", "metrics": {}}
    ).status_code == 401


def test_device_commands_keep_device_key_only(client, locked, db):
    db.add(models.Device(code="relay-1", name="Relay", kind="light"))
    db.commit()
    assert client.get("/api/devices/relay-1/commands", headers=DEVICE_KEY).status_code == 200
    assert client.get("/api/devices/relay-1/commands").status_code == 401


def test_health_is_public(client, locked):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["cloud_sink"]["enabled"] is False


def test_websocket_without_token_closes_with_4401(client, locked):
    with client.websocket_connect("/ws") as ws:
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_text()
    assert closed.value.code == 4401

    with client.websocket_connect("/ws?token=bad") as ws:
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_text()
    assert closed.value.code == 4401


def test_websocket_with_token_stays_open(client, locked):
    token = _login(client).json()["token"]
    with client.websocket_connect(f"/ws?token={token}") as ws:
        ws.send_text("ping")  # accepted connection; closing it from the client side is fine


def test_empty_password_keeps_open_behaviour(client):
    assert settings.dashboard_password == ""
    assert client.get("/api/devices").status_code == 200
    assert client.get("/api/auth/me").status_code == 200
    with client.websocket_connect("/ws") as ws:
        ws.send_text("ping")
