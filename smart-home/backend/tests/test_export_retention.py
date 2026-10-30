from datetime import date

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from sqlalchemy import func, select

from app import analytics, models, services
from app.config import settings
from conftest import add_reading, utc


@pytest.fixture
def lake(tmp_path):
    return tmp_path / "lake"


def _raw_count(db, day: date) -> int:
    return db.scalar(
        select(func.count(models.Reading.id)).where(
            func.date(models.Reading.ts) == day.isoformat()
        )
    )


def test_export_writes_partition_with_schema_and_rows(db, device, lake):
    add_reading(db, device, "humidity", 61.0, utc(2026, 10, 28, 23, 59, 50))
    add_reading(db, device, "temperature", 27.5, utc(2026, 10, 28, 0, 0, 0))
    add_reading(db, device, "temperature", 28.0, utc(2026, 10, 28, 12, 0, 0))
    add_reading(db, device, "temperature", 99.0, utc(2026, 10, 29, 0, 0, 0))  # next day
    db.commit()

    path = analytics.export_day(db, date(2026, 10, 28), lake_dir=lake)

    assert path == lake / "readings" / "date=2026-10-28" / "part-0.parquet"
    table = pq.read_table(path)
    assert table.schema.equals(analytics.PARQUET_SCHEMA)
    assert table.num_rows == 3 == _raw_count(db, date(2026, 10, 28))
    # Values are stored as UTC; cast away the tz because converting tz-aware scalars
    # to Python needs the tzdata package on Windows
    stamps = table.column("ts").cast(pa.timestamp("us")).to_pylist()
    assert stamps == sorted(stamps)
    assert stamps[0] == utc(2026, 10, 28, 0, 0, 0).replace(tzinfo=None)
    first = table.drop_columns(["ts"]).slice(0, 1).to_pylist()[0]
    assert first == {"device_code": "esp32-main", "metric": "temperature", "value": 27.5}
    assert not path.with_name("part-0.parquet.tmp").exists()


def test_export_skips_existing_partition_unless_forced(db, device, lake):
    add_reading(db, device, "temperature", 20.0, utc(2026, 10, 28, 1))
    db.commit()
    path = analytics.export_day(db, date(2026, 10, 28), lake_dir=lake)

    add_reading(db, device, "temperature", 21.0, utc(2026, 10, 28, 2))
    db.commit()
    assert analytics.export_day(db, date(2026, 10, 28), lake_dir=lake) is None
    assert pq.ParquetFile(path).metadata.num_rows == 1

    assert analytics.export_day(db, date(2026, 10, 28), force=True, lake_dir=lake) == path
    assert pq.ParquetFile(path).metadata.num_rows == 2


def test_export_of_empty_day_writes_nothing(db, device, lake):
    assert analytics.export_day(db, date(2026, 10, 28), lake_dir=lake) is None
    assert not (lake / "readings" / "date=2026-10-28").exists()


def test_orphan_tmp_file_is_ignored(db, device, lake):
    add_reading(db, device, "temperature", 20.0, utc(2026, 10, 29, 6))
    db.commit()
    folder = lake / "readings" / "date=2026-10-29"
    folder.mkdir(parents=True)
    (folder / "part-0.parquet.tmp").write_bytes(b"half-written")

    assert analytics.lake_partitions(lake) == []

    exported = analytics.export_missing_days(db, utc(2026, 10, 30, 0, 15), lake_dir=lake)

    assert exported == [date(2026, 10, 29)]
    assert not (folder / "part-0.parquet.tmp").exists()
    assert analytics.lake_partitions(lake) == [
        {
            "date": date(2026, 10, 29),
            "rows": 1,
            "bytes": (folder / "part-0.parquet").stat().st_size,
        }
    ]


def test_export_missing_days_skips_today(db, device, lake):
    add_reading(db, device, "temperature", 20.0, utc(2026, 10, 29, 6))
    add_reading(db, device, "temperature", 20.0, utc(2026, 10, 30, 0, 5))
    db.commit()

    assert analytics.export_missing_days(db, utc(2026, 10, 30, 0, 15), lake_dir=lake) == [
        date(2026, 10, 29)
    ]
    assert [p["date"] for p in analytics.lake_partitions(lake)] == [date(2026, 10, 29)]


def test_retention_deletes_raw_rows_only_for_exported_days(db, device, lake, monkeypatch):
    monkeypatch.setattr(settings, "raw_retention_days", 1)
    now = utc(2026, 10, 30, 1, 0)  # cutoff 2026-10-29 01:00
    for day in (26, 27, 28):
        add_reading(db, device, "temperature", 20.0, utc(2026, 10, day, 6))
        add_reading(db, device, "temperature", 21.0, utc(2026, 10, day, 18))
    add_reading(db, device, "temperature", 22.0, utc(2026, 10, 29, 0, 30))
    db.commit()
    analytics.run_rollups(db, now)
    db.commit()

    analytics.export_day(db, date(2026, 10, 27), lake_dir=lake)
    analytics.export_day(db, date(2026, 10, 29), lake_dir=lake)

    deleted = analytics.run_retention(db, now, lake_dir=lake)
    db.commit()

    assert deleted == 2 + 1
    assert _raw_count(db, date(2026, 10, 26)) == 2  # no partition: kept
    assert _raw_count(db, date(2026, 10, 27)) == 0
    assert _raw_count(db, date(2026, 10, 28)) == 2  # no partition: kept
    assert _raw_count(db, date(2026, 10, 29)) == 0  # 00:30 is older than the cutoff
    # 1h rollups are kept forever
    assert db.scalar(
        select(func.count()).select_from(models.ReadingRollup).where(
            models.ReadingRollup.bucket == "1h"
        )
    ) == 7


def test_early_export_is_redone_and_never_licenses_deletes(db, device, lake, monkeypatch):
    """A manual export taken mid-day must not lose the rows written after it."""
    monkeypatch.setattr(settings, "raw_retention_days", 1)
    add_reading(db, device, "temperature", 20.0, utc(2026, 10, 27, 10))
    db.commit()
    analytics.export_day(db, date(2026, 10, 27), force=True, lake_dir=lake)  # at 10:00
    add_reading(db, device, "temperature", 21.0, utc(2026, 10, 27, 20))
    db.commit()
    now = utc(2026, 10, 30, 1)
    analytics.run_rollups(db, now)

    # Retention alone refuses: the partition has fewer rows than the database
    assert analytics.run_retention(db, now, lake_dir=lake) == 0
    assert _raw_count(db, date(2026, 10, 27)) == 2

    # The daily export redoes the closed day, after which retention may delete
    assert analytics.export_missing_days(db, now, lake_dir=lake) == [date(2026, 10, 27)]
    path = analytics.partition_path(date(2026, 10, 27), lake)
    assert pq.ParquetFile(path).metadata.num_rows == 2
    assert analytics.run_retention(db, now, lake_dir=lake) == 2

    # Fewer raw rows than the partition (retention ran) does not trigger a re-export
    assert analytics.export_missing_days(db, now, lake_dir=lake) == []
    assert pq.ParquetFile(path).metadata.num_rows == 2


def test_retention_waits_for_hourly_rollups(db, device, lake, monkeypatch):
    monkeypatch.setattr(settings, "raw_retention_days", 1)
    add_reading(db, device, "temperature", 20.0, utc(2026, 10, 27, 6))
    db.commit()
    analytics.export_day(db, date(2026, 10, 27), lake_dir=lake)

    assert analytics.run_retention(db, utc(2026, 10, 30, 1), lake_dir=lake) == 0
    assert _raw_count(db, date(2026, 10, 27)) == 1


def test_retention_prunes_old_1m_rollups(db, device, lake):
    for start in (utc(2026, 9, 1, 10), utc(2026, 10, 29, 10)):
        for bucket in ("1m", "1h"):
            db.add(
                models.ReadingRollup(
                    device_id=device.id, metric="gas", bucket=bucket, bucket_start=start,
                    count=1, min=1, max=1, avg=1,
                )
            )
    db.commit()

    analytics.run_retention(db, utc(2026, 10, 30, 1), lake_dir=lake)
    db.commit()

    left = db.execute(
        select(models.ReadingRollup.bucket, models.ReadingRollup.bucket_start).order_by(
            models.ReadingRollup.bucket, models.ReadingRollup.bucket_start
        )
    ).all()
    assert [(bucket, services.as_utc(start)) for bucket, start in left] == [
        ("1h", utc(2026, 9, 1, 10)),
        ("1h", utc(2026, 10, 29, 10)),
        ("1m", utc(2026, 10, 29, 10)),
    ]
