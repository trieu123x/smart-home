import asyncio
from datetime import timedelta

from sqlalchemy import select

from app import analytics, models
from conftest import DEVICE_KEY, add_reading, utc

NOW = utc(2026, 10, 30, 12, 0, 30)
CURRENT = utc(2026, 10, 30, 11, 59)  # newest closed minute at NOW


def _bucket(db, device, start, avg, metric="temperature"):
    db.add(
        models.ReadingRollup(
            device_id=device.id, metric=metric, bucket="1m", bucket_start=start,
            count=6, min=avg, max=avg, avg=avg,
        )
    )


def _baseline(db, device, minutes: int, values=(28.0, 28.2), end=CURRENT):
    for i in range(1, minutes + 1):
        _bucket(db, device, end - timedelta(minutes=i), values[i % len(values)])


def _anomalies(db) -> list[models.Event]:
    return db.scalars(select(models.Event).where(models.Event.type == "anomaly")).all()


def _detect(db, now=NOW):
    events = asyncio.run(analytics.detect_anomalies(db, now))
    db.commit()
    return events


def test_spike_creates_one_anomaly_event(db, device):
    _baseline(db, device, 120)
    _bucket(db, device, CURRENT, 41.2)
    db.commit()

    events = _detect(db)

    assert len(events) == 1
    event = _anomalies(db)[0]
    assert event.severity == "warning"
    assert event.device_id == device.id
    assert event.message.startswith("Bất thường: nhiệt độ 41.2 (z=")
    assert event.message.endswith(", TB 24h 28.1)")

    # The same bucket is not judged twice
    assert _detect(db) == []
    assert len(_anomalies(db)) == 1


def test_second_spike_within_cooldown_creates_no_event(db, device):
    _baseline(db, device, 120)
    _bucket(db, device, CURRENT, 41.2)
    db.commit()
    assert len(_detect(db)) == 1

    _bucket(db, device, CURRENT + timedelta(minutes=1), 42.0)
    db.commit()
    assert _detect(db, NOW + timedelta(minutes=1)) == []

    # After the 15 min cooldown a new spike fires again
    _bucket(db, device, CURRENT + timedelta(minutes=16), 42.0)
    db.commit()
    assert len(_detect(db, NOW + timedelta(minutes=16))) == 1
    assert len(_anomalies(db)) == 2


def test_negative_spike_also_counts(db, device):
    _baseline(db, device, 120)
    _bucket(db, device, CURRENT, 10.0)
    db.commit()
    assert len(_detect(db)) == 1


def test_fewer_than_60_baseline_buckets_creates_no_event(db, device):
    _baseline(db, device, 59)
    _bucket(db, device, CURRENT, 41.2)
    db.commit()
    assert _detect(db) == []


def test_zero_std_creates_no_event(db, device):
    _baseline(db, device, 120, values=(28.0,))
    _bucket(db, device, CURRENT, 41.2)
    db.commit()
    assert _detect(db) == []


def test_motion_is_not_checked(db, device):
    for i in range(1, 121):
        _bucket(db, device, CURRENT - timedelta(minutes=i), float(i % 2), metric="motion")
    _bucket(db, device, CURRENT, 50.0, metric="motion")
    db.commit()
    assert _detect(db) == []


def test_stale_bucket_is_not_checked(db, device):
    old = CURRENT - timedelta(hours=1)
    _baseline(db, device, 120, end=old)
    _bucket(db, device, old, 41.2)
    db.commit()
    assert _detect(db) == []


def test_spike_through_ingest_creates_one_event(db, device, client):
    """End to end: raw baseline -> ingest spike -> tick (rollup + detect)."""
    start = CURRENT - timedelta(hours=2)
    for minute in range(120):
        for second in (0, 30):
            ts = start + timedelta(minutes=minute, seconds=second)
            add_reading(db, device, "temperature", 28.0 + (minute % 3) * 0.1, ts)
    db.commit()

    for second in (5, 25, 45):
        response = client.post(
            "/api/ingest/telemetry",
            headers=DEVICE_KEY,
            json={
                "device_code": "esp32-main",
                "metrics": {"temperature": 45.0},
                "ts": (CURRENT + timedelta(seconds=second)).isoformat(),
            },
        )
        assert response.status_code == 202

    asyncio.run(analytics.tick(db, NOW))
    asyncio.run(analytics.tick(db, NOW + timedelta(minutes=1)))

    events = _anomalies(db)
    assert len(events) == 1
    assert events[0].message.startswith("Bất thường: nhiệt độ 45.0")
