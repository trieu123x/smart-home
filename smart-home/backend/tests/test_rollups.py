from datetime import timedelta

from sqlalchemy import select

from app import analytics, models, services
from conftest import add_reading, utc


def _rollups(db, bucket: str) -> list[tuple]:
    rows = db.scalars(
        select(models.ReadingRollup)
        .where(models.ReadingRollup.bucket == bucket)
        .order_by(models.ReadingRollup.metric, models.ReadingRollup.bucket_start)
    ).all()
    return [
        (row.metric, services.as_utc(row.bucket_start), row.count, row.min, row.max, row.avg)
        for row in rows
    ]


def test_1m_and_1h_aggregates_match_hand_computed(db, device):
    add_reading(db, device, "temperature", 1.0, utc(2026, 10, 30, 10, 0, 5))
    add_reading(db, device, "temperature", 3.0, utc(2026, 10, 30, 10, 0, 35))
    add_reading(db, device, "temperature", 10.0, utc(2026, 10, 30, 10, 1, 10))
    add_reading(db, device, "humidity", 60.0, utc(2026, 10, 30, 10, 0, 50))
    db.commit()

    analytics.run_rollups(db, utc(2026, 10, 30, 11, 0, 30))
    db.commit()

    assert _rollups(db, "1m") == [
        ("humidity", utc(2026, 10, 30, 10, 0), 1, 60.0, 60.0, 60.0),
        ("temperature", utc(2026, 10, 30, 10, 0), 2, 1.0, 3.0, 2.0),
        ("temperature", utc(2026, 10, 30, 10, 1), 1, 10.0, 10.0, 10.0),
    ]
    hourly = _rollups(db, "1h")
    assert hourly[0] == ("humidity", utc(2026, 10, 30, 10), 1, 60.0, 60.0, 60.0)
    metric, start, count, low, high, mean = hourly[1]
    assert (metric, start, count, low, high) == ("temperature", utc(2026, 10, 30, 10), 3, 1.0, 10.0)
    assert abs(mean - 14 / 3) < 1e-9


def test_rerun_is_idempotent(db, device):
    start = utc(2026, 10, 30, 10)
    for second in range(0, 600, 10):  # ten minutes, one reading every 10 s
        add_reading(db, device, "temperature", 20 + second / 100, start + timedelta(seconds=second))
    db.commit()
    now = utc(2026, 10, 30, 11, 5)

    analytics.run_rollups(db, now)
    db.commit()
    first = (_rollups(db, "1m"), _rollups(db, "1h"))

    analytics.run_rollups(db, now)
    analytics.run_rollups(db, now)
    db.commit()
    second = (_rollups(db, "1m"), _rollups(db, "1h"))

    assert first == second
    assert len(first[0]) == 10
    assert len(first[1]) == 1


def test_open_bucket_is_not_written(db, device):
    add_reading(db, device, "temperature", 20.0, utc(2026, 10, 30, 10, 1, 10))
    add_reading(db, device, "temperature", 30.0, utc(2026, 10, 30, 10, 2, 10))  # open minute
    db.commit()

    analytics.run_rollups(db, utc(2026, 10, 30, 10, 2, 30))
    db.commit()

    assert [row[1] for row in _rollups(db, "1m")] == [utc(2026, 10, 30, 10, 1)]
    assert _rollups(db, "1h") == []  # the 10:00 hour is still open


def test_late_row_in_watermark_bucket_is_merged(db, device):
    add_reading(db, device, "temperature", 20.0, utc(2026, 10, 30, 10, 1, 10))
    db.commit()
    analytics.run_rollups(db, utc(2026, 10, 30, 10, 2, 0))
    add_reading(db, device, "temperature", 30.0, utc(2026, 10, 30, 10, 1, 50))
    db.commit()

    analytics.run_rollups(db, utc(2026, 10, 30, 10, 3, 0))
    db.commit()

    assert _rollups(db, "1m") == [
        ("temperature", utc(2026, 10, 30, 10, 1), 2, 20.0, 30.0, 25.0)
    ]


def test_catch_up_after_gap_of_several_hours(db, device):
    add_reading(db, device, "temperature", 20.0, utc(2026, 10, 30, 8, 0, 10))
    db.commit()
    analytics.run_rollups(db, utc(2026, 10, 30, 8, 30))
    db.commit()
    assert len(_rollups(db, "1m")) == 1

    # Laptop off for five hours, then data again
    add_reading(db, device, "temperature", 25.0, utc(2026, 10, 30, 13, 30, 10))
    db.commit()
    analytics.run_rollups(db, utc(2026, 10, 30, 14, 0, 5))
    db.commit()

    assert [row[1] for row in _rollups(db, "1m")] == [
        utc(2026, 10, 30, 8, 0),
        utc(2026, 10, 30, 13, 30),
    ]
    assert [row[1] for row in _rollups(db, "1h")] == [
        utc(2026, 10, 30, 8),
        utc(2026, 10, 30, 13),
    ]


def test_backfill_spans_several_days(db, device):
    for day in (27, 28, 29):
        add_reading(db, device, "gas", float(day), utc(2026, 10, day, 12, 0, 0))
    db.commit()

    analytics.run_rollups(db, utc(2026, 10, 30, 0, 5))
    db.commit()

    assert [row[1] for row in _rollups(db, "1h")] == [
        utc(2026, 10, 27, 12),
        utc(2026, 10, 28, 12),
        utc(2026, 10, 29, 12),
    ]


def test_empty_database_does_nothing(db):
    assert analytics.run_rollups(db, utc(2026, 10, 30, 12)) == {"1m": 0, "1h": 0}
