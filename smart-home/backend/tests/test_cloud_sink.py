import asyncio
import time

import httpx
import pytest

from app import cloud_sink
from app.config import settings
from conftest import utc

URL = "https://sink.example.test/api/v1/push/influx/write"


@pytest.fixture
def sink(monkeypatch):
    monkeypatch.setattr(settings, "cloud_sink_enabled", True)
    monkeypatch.setattr(settings, "cloud_sink_url", URL)
    monkeypatch.setattr(settings, "cloud_sink_user", "123456")
    monkeypatch.setattr(settings, "cloud_sink_token", "glc_token")
    cloud_sink.reset()
    return cloud_sink


def _flush(handler) -> list[httpx.Request]:
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(record)) as client:
            await cloud_sink.flush(client)

    asyncio.run(run())
    return seen


def test_line_format_and_ns_timestamp():
    line = cloud_sink.format_line(
        "esp32-main",
        {"temperature": 27.5, "humidity": 61.0, "ldr": 1203.0, "gas": 180.0, "motion": 0.0},
        utc(2025, 10, 30, 5, 13, 20, 123456),
    )
    assert line == (
        "smarthome,device=esp32-main "
        "temperature=27.5,humidity=61,ldr=1203,gas=180,motion=0 1761801200123456000"
    )


def test_line_format_skips_non_finite_and_escapes_tags():
    line = cloud_sink.format_line("my device,1", {"a": float("nan"), "b": 2.0}, utc(2026, 1, 1))
    assert line.startswith("smarthome,device=my\\ device\\,1 b=2 ")
    assert cloud_sink.format_line("x", {"a": float("inf")}, utc(2026, 1, 1)) is None


def test_line_breaks_cannot_inject_extra_lines():
    line = cloud_sink.format_line("a\nsmarthome,device=b", {"t\r\n": 1.0}, utc(2026, 1, 1))
    assert "\n" not in line and "\r" not in line
    assert line.startswith("smarthome,device=asmarthome\\,device\\=b t=1 ")


def test_disabled_sink_buffers_nothing():
    cloud_sink.enqueue("esp32-main", {"temperature": 1.0}, utc(2026, 1, 1))
    assert cloud_sink.status()["pending"] == 0
    assert cloud_sink.status()["enabled"] is False


def test_2xx_drains_buffer(sink):
    for second in range(3):
        sink.enqueue("esp32-main", {"temperature": 20.0 + second}, utc(2026, 1, 1, 0, 0, second))

    seen = _flush(lambda request: httpx.Response(204))

    assert len(seen) == 1
    assert seen[0].content.decode().count("\n") == 2
    assert seen[0].headers["Authorization"].startswith("Basic ")
    status = sink.status()
    assert status["pending"] == 0
    assert status["last_ok"].endswith("Z")
    assert status["dropped"] == 0


def test_token_auth_without_user(sink, monkeypatch):
    monkeypatch.setattr(settings, "cloud_sink_user", "")
    sink.enqueue("esp32-main", {"temperature": 20.0}, utc(2026, 1, 1))
    seen = _flush(lambda request: httpx.Response(204))
    assert seen[0].headers["Authorization"] == "Token glc_token"


def test_batch_is_capped(sink):
    for i in range(cloud_sink.MAX_BATCH + 5):
        sink.enqueue("esp32-main", {"temperature": float(i)}, utc(2026, 1, 1))
    seen = _flush(lambda request: httpx.Response(204))
    assert seen[0].content.decode().count("\n") == cloud_sink.MAX_BATCH - 1
    assert sink.status()["pending"] == 5


def test_503_keeps_batch_and_backs_off(sink):
    sink.enqueue("esp32-main", {"temperature": 20.0}, utc(2026, 1, 1))

    seen = _flush(lambda request: httpx.Response(503))
    assert len(seen) == 1
    assert sink.status()["pending"] == 1
    assert sink.status()["last_error"] == "HTTP 503"
    assert 9 <= cloud_sink._retry_at - time.monotonic() <= 10

    # Still backing off: no request is sent
    assert _flush(lambda request: httpx.Response(204)) == []
    assert sink.status()["pending"] == 1

    # Next failure doubles the delay
    cloud_sink._retry_at = 0.0
    _flush(lambda request: httpx.Response(503))
    assert 19 <= cloud_sink._retry_at - time.monotonic() <= 20


def test_429_honours_retry_after(sink):
    sink.enqueue("esp32-main", {"temperature": 20.0}, utc(2026, 1, 1))
    _flush(lambda request: httpx.Response(429, headers={"Retry-After": "30"}))
    assert sink.status()["pending"] == 1
    assert 29 <= cloud_sink._retry_at - time.monotonic() <= 30


def test_connection_error_keeps_batch(sink):
    sink.enqueue("esp32-main", {"temperature": 20.0}, utc(2026, 1, 1))

    def fail(request):
        raise httpx.ConnectError("unreachable", request=request)

    _flush(fail)
    assert sink.status()["pending"] == 1
    assert "ConnectError" in sink.status()["last_error"]


def test_400_drops_batch_and_counts_it(sink):
    for second in range(4):
        sink.enqueue("esp32-main", {"temperature": 20.0}, utc(2026, 1, 1, 0, 0, second))

    _flush(lambda request: httpx.Response(400, text="bad field"))

    status = sink.status()
    assert status["pending"] == 0
    assert status["dropped"] == 4
    assert status["last_error"] == "HTTP 400: bad field"
    assert cloud_sink._retry_at == 0.0  # no back-off: the next batch goes out normally


def test_full_buffer_drops_oldest(sink, monkeypatch):
    monkeypatch.setattr(settings, "cloud_sink_max_buffer", 3)
    cloud_sink.reset()
    for value in range(5):
        cloud_sink.enqueue("esp32-main", {"temperature": float(value)}, utc(2026, 1, 1))

    status = cloud_sink.status()
    assert status["pending"] == 3
    assert status["dropped"] == 2
    assert [line.split(" ")[1] for line in cloud_sink._buffer] == [
        "temperature=2",
        "temperature=3",
        "temperature=4",
    ]
