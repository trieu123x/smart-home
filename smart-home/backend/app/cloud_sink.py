"""Push stored readings to a cloud time-series database using Influx line protocol.

Works with Grafana Cloud's Influx endpoint (Basic auth, CLOUD_SINK_USER set) and with
InfluxDB v2/v3 `/api/v2/write?bucket=...&precision=ns` (Token auth). Readings are
buffered in memory and sent in batches from `background_worker`; the local SQLite
database stays the source of truth, so a restart may lose what is still buffered.
"""

import itertools
import math
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from .config import settings

MEASUREMENT = "smarthome"
MAX_BATCH = 1000
TIMEOUT_SECONDS = 10.0
BACKOFF_STEPS = (10, 20, 40, 60)
MAX_RETRY_AFTER = 3600

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)

_buffer: deque[str] = deque(maxlen=max(1, settings.cloud_sink_max_buffer))
_dropped = 0
# Lines pushed out of the full buffer; lets flush() tell how much of its batch is already gone
_evicted = 0
_failures = 0
_retry_at = 0.0  # time.monotonic() before which flush() does nothing
_last_ok: datetime | None = None
_last_error: str | None = None


def _log(message: str) -> None:
    print(f"[cloud-sink] {message}", flush=True)


def _escape(text: str) -> str:
    """Escape a tag value or field key (commas, spaces and equals signs).

    Line breaks cannot be escaped in line protocol; drop them so one value cannot
    split into an extra, spoofed line."""
    text = text.replace("\r", "").replace("\n", "")
    return text.replace("\\", "\\\\").replace(",", "\\,").replace(" ", "\\ ").replace("=", "\\=")


def _ns(ts: datetime) -> int:
    ts = ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    return (ts - _EPOCH) // timedelta(microseconds=1) * 1000


def format_line(device_code: str, fields: dict[str, float], ts: datetime) -> str | None:
    """One line per device per timestamp, or None when no field is a finite number."""
    parts = [
        f"{_escape(metric)}={format(float(value), '.15g')}"
        for metric, value in fields.items()
        if value is not None and math.isfinite(float(value))
    ]
    if not parts:
        return None
    return f"{MEASUREMENT},device={_escape(device_code)} {','.join(parts)} {_ns(ts)}"


def enqueue(device_code: str, fields: dict[str, float], ts: datetime) -> None:
    """Queue one line; O(1). When the buffer is full the oldest line is dropped."""
    global _dropped, _evicted
    if not settings.cloud_sink_enabled:
        return
    line = format_line(device_code, fields, ts)
    if line is None:
        return
    if len(_buffer) == _buffer.maxlen:
        _dropped += 1
        _evicted += 1
    _buffer.append(line)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat().replace("+00:00", "Z") if value else None


def status() -> dict[str, Any]:
    return {
        "enabled": settings.cloud_sink_enabled,
        "pending": len(_buffer),
        "dropped": _dropped,
        "last_ok": _iso(_last_ok),
        "last_error": _last_error,
    }


def _retry_after(response: httpx.Response | None) -> float | None:
    if response is None:
        return None
    try:
        seconds = float(response.headers.get("Retry-After", ""))
    except ValueError:
        return None  # HTTP-date form is not worth parsing here
    return min(max(seconds, 0.0), MAX_RETRY_AFTER)


def _back_off(error: str, response: httpx.Response | None = None) -> None:
    global _failures, _retry_at, _last_error
    delay = _retry_after(response)
    if delay is None:
        delay = BACKOFF_STEPS[min(_failures, len(BACKOFF_STEPS) - 1)]
    _failures += 1
    _retry_at = time.monotonic() + delay
    _last_error = error
    _log(f"{error}; retry in {delay:g}s ({len(_buffer)} pending)")


def _remove_sent(count: int, evicted_before: int) -> int:
    """Pop the batch from the buffer, minus lines the full buffer already evicted (and counted)."""
    already_gone = min(count, _evicted - evicted_before)
    removed = min(count - already_gone, len(_buffer))
    for _ in range(removed):
        _buffer.popleft()
    return removed


def _request_kwargs() -> dict[str, Any]:
    headers = {"Content-Type": "text/plain; charset=utf-8"}
    if settings.cloud_sink_user:
        return {"headers": headers, "auth": (settings.cloud_sink_user, settings.cloud_sink_token)}
    headers["Authorization"] = f"Token {settings.cloud_sink_token}"
    return {"headers": headers}


async def flush(client: httpx.AsyncClient | None = None) -> None:
    """POST at most MAX_BATCH buffered lines. `client` is injectable for tests."""
    global _failures, _retry_at, _last_ok, _last_error, _dropped
    if not settings.cloud_sink_enabled or not settings.cloud_sink_url or not _buffer:
        return
    if time.monotonic() < _retry_at:
        return

    batch = list(itertools.islice(_buffer, MAX_BATCH))
    evicted_before = _evicted
    body = "\n".join(batch)
    try:
        if client is None:
            async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as own_client:
                response = await own_client.post(
                    settings.cloud_sink_url, content=body, **_request_kwargs()
                )
        else:
            response = await client.post(
                settings.cloud_sink_url, content=body, timeout=TIMEOUT_SECONDS, **_request_kwargs()
            )
    except Exception as exc:  # e.g. InvalidURL too: this runs as a fire-and-forget task
        _back_off(f"{type(exc).__name__}: {exc}")
        return

    code = response.status_code
    if 200 <= code < 300:
        _remove_sent(len(batch), evicted_before)
        _failures = 0
        _retry_at = 0.0
        _last_ok = datetime.now(timezone.utc)
    elif code == 429 or code >= 500:
        _back_off(f"HTTP {code}", response)
    else:
        # Bad data will not fix itself: drop the batch so one bad line cannot block the queue
        removed = _remove_sent(len(batch), evicted_before)
        _dropped += removed
        _last_error = f"HTTP {code}: {response.text[:200]}"
        _log(f"dropped {removed} lines, {_last_error}")


def reset() -> None:
    """Clear buffer and counters (used by tests)."""
    global _buffer, _dropped, _evicted, _failures, _retry_at, _last_ok, _last_error
    _buffer = deque(maxlen=max(1, settings.cloud_sink_max_buffer))
    _dropped = _evicted = _failures = 0
    _retry_at = 0.0
    _last_ok = _last_error = None
