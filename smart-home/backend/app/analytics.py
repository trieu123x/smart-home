"""Local analytics pipeline: rollups, Parquet lake export, retention and anomaly events.

Driven from `background_worker` by wall-clock checks (`tick`): rollups and anomaly
detection once a minute, export and retention once a day after 00:10 UTC. All buckets
and partitions use UTC. Also a small CLI:

    python -m app.analytics export --date 2026-10-29 [--force]
    python -m app.analytics rollup
"""

import argparse
import os
import statistics
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from . import models, services
from .config import settings

BUCKETS = {"1m": 60, "1h": 3600}
_BUCKET_FORMAT = {"1m": "%Y-%m-%d %H:%M:00", "1h": "%Y-%m-%d %H:00:00"}
ROLLUP_1M_RETENTION_DAYS = 30
DAILY_JOB_AFTER = time(0, 10)

ANOMALY_METRICS = ("temperature", "humidity", "gas", "ldr")
ANOMALY_LABEL = {
    "temperature": "nhiệt độ",
    "humidity": "độ ẩm",
    "gas": "khí gas",
    "ldr": "ánh sáng",
}
ANOMALY_MIN_BASELINE = 60
ANOMALY_COOLDOWN = timedelta(minutes=15)
# Only judge buckets this recent, so a stale last bucket does not keep firing
ANOMALY_MAX_AGE = timedelta(minutes=5)

PARQUET_SCHEMA = pa.schema(
    [
        ("device_code", pa.string()),
        ("metric", pa.string()),
        ("value", pa.float64()),
        ("ts", pa.timestamp("us", tz="UTC")),
    ]
)

# In-memory scheduler and cooldown state (single background_worker task)
_last_minute: datetime | None = None
_last_daily: date | None = None
_anomaly_last_event: dict[tuple[int, str], datetime] = {}
_anomaly_last_checked: dict[tuple[int, str], datetime] = {}


def _log(message: str) -> None:
    print(f"[analytics] {message}", flush=True)


def floor_time(value: datetime, seconds: int) -> datetime:
    value = services.as_utc(value)
    stamp = int(value.timestamp())
    return datetime.fromtimestamp(stamp - stamp % seconds, tz=timezone.utc)


def _day_start(day: date) -> datetime:
    return datetime.combine(day, time(0), tzinfo=timezone.utc)


def lake_root(lake_dir: str | os.PathLike | None = None) -> Path:
    return Path(lake_dir if lake_dir is not None else settings.lake_dir) / "readings"


def partition_path(day: date, lake_dir: str | os.PathLike | None = None) -> Path:
    return lake_root(lake_dir) / f"date={day.isoformat()}" / "part-0.parquet"


# ---------------------------------------------------------------- rollups
def _watermark(db: Session, bucket: str) -> datetime | None:
    """Newest bucket_start already stored for this bucket size."""
    value = db.scalar(
        select(func.max(models.ReadingRollup.bucket_start)).where(
            models.ReadingRollup.bucket == bucket
        )
    )
    return services.as_utc(value)


def _rollup_range(db: Session, bucket: str, start: datetime, end: datetime) -> int:
    """Aggregate raw readings in [start, end) into `bucket` rows; upsert so re-runs are idempotent."""
    bucket_expr = func.strftime(_BUCKET_FORMAT[bucket], models.Reading.ts).label("bucket_start")
    rows = db.execute(
        select(
            models.Reading.device_id,
            models.Reading.metric,
            bucket_expr,
            func.count(models.Reading.id),
            func.min(models.Reading.value),
            func.max(models.Reading.value),
            func.avg(models.Reading.value),
        )
        .where(models.Reading.ts >= start, models.Reading.ts < end)
        .group_by(models.Reading.device_id, models.Reading.metric, bucket_expr)
    ).all()
    if not rows:
        return 0

    values = [
        {
            "device_id": device_id,
            "metric": metric,
            "bucket": bucket,
            "bucket_start": datetime.strptime(start_text, "%Y-%m-%d %H:%M:%S").replace(
                tzinfo=timezone.utc
            ),
            "count": count,
            "min": float(low),
            "max": float(high),
            "avg": float(mean),
        }
        for device_id, metric, start_text, count, low, high, mean in rows
    ]
    # executemany form: a single multi-VALUES insert would exceed SQLite's parameter limit
    statement = sqlite_insert(models.ReadingRollup)
    statement = statement.on_conflict_do_update(
        index_elements=["device_id", "metric", "bucket", "bucket_start"],
        set_={
            "count": statement.excluded.count,
            "min": statement.excluded.min,
            "max": statement.excluded.max,
            "avg": statement.excluded.avg,
        },
    )
    db.execute(statement, values)
    return len(values)


def run_rollups(db: Session, now: datetime) -> dict[str, int]:
    """Roll up every fully closed bucket since the watermark (or the oldest raw row)."""
    written: dict[str, int] = {}
    for bucket, seconds in BUCKETS.items():
        end = floor_time(now, seconds)
        start = _watermark(db, bucket)
        if start is None:
            oldest = db.scalar(select(func.min(models.Reading.ts)))
            if oldest is None:
                written[bucket] = 0
                continue
            start = floor_time(oldest, seconds)
        total = 0
        # Re-aggregate the watermark bucket too: late rows may have landed in it
        chunk_start = start
        while chunk_start < end:
            chunk_end = min(chunk_start + timedelta(days=1), end)
            total += _rollup_range(db, bucket, chunk_start, chunk_end)
            chunk_start = chunk_end
        written[bucket] = total
    db.flush()
    return written


# ---------------------------------------------------------------- Parquet export
def export_day(
    db: Session,
    day: date,
    *,
    force: bool = False,
    lake_dir: str | os.PathLike | None = None,
) -> Path | None:
    """Write one UTC day of raw readings to the lake. Returns None when skipped or empty."""
    path = partition_path(day, lake_dir)
    if path.exists() and not force:
        return None

    start = _day_start(day)
    rows = db.execute(
        select(models.Device.code, models.Reading.metric, models.Reading.value, models.Reading.ts)
        .join(models.Device, models.Device.id == models.Reading.device_id)
        .where(models.Reading.ts >= start, models.Reading.ts < start + timedelta(days=1))
        .order_by(models.Reading.ts, models.Reading.id)
    ).all()
    if not rows:
        return None

    table = pa.table(
        {
            "device_code": [row[0] for row in rows],
            "metric": [row[1] for row in rows],
            "value": [float(row[2]) for row in rows],
            "ts": [services.as_utc(row[3]) for row in rows],
        },
        schema=PARQUET_SCHEMA,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    pq.write_table(table, tmp)
    os.replace(tmp, path)
    return path


def _raw_days_before(db: Session, before: datetime) -> list[date]:
    texts = db.scalars(
        select(func.date(models.Reading.ts))
        .where(models.Reading.ts < before)
        .distinct()
        .order_by(func.date(models.Reading.ts))
    ).all()
    return [date.fromisoformat(text) for text in texts if text]


def _raw_count(db: Session, day: date) -> int:
    start = _day_start(day)
    return db.scalar(
        select(func.count(models.Reading.id)).where(
            models.Reading.ts >= start, models.Reading.ts < start + timedelta(days=1)
        )
    ) or 0


def _partition_rows(path: Path) -> int:
    return pq.ParquetFile(path).metadata.num_rows


def export_missing_days(
    db: Session, now: datetime, lake_dir: str | os.PathLike | None = None
) -> list[date]:
    """Export every closed UTC day that has no partition, or whose partition has fewer
    rows than the database (e.g. a manual export taken before the day was over).
    Fewer raw rows than the partition just means retention already ran: keep it."""
    today = _day_start(services.as_utc(now).date())
    exported = []
    for day in _raw_days_before(db, today):
        path = partition_path(day, lake_dir)
        stale = path.exists() and _partition_rows(path) < _raw_count(db, day)
        if (not path.exists() or stale) and export_day(db, day, force=stale, lake_dir=lake_dir):
            exported.append(day)
    return exported


def lake_partitions(lake_dir: str | os.PathLike | None = None) -> list[dict]:
    """Existing partitions, newest first. An orphan .tmp file is not a partition."""
    root = lake_root(lake_dir)
    if not root.is_dir():
        return []
    result = []
    for folder in root.glob("date=*"):
        path = folder / "part-0.parquet"
        try:
            day = date.fromisoformat(folder.name.removeprefix("date="))
        except ValueError:
            continue
        if not path.is_file():
            continue
        result.append(
            {
                "date": day,
                "rows": pq.ParquetFile(path).metadata.num_rows,
                "bytes": path.stat().st_size,
            }
        )
    result.sort(key=lambda item: item["date"], reverse=True)
    return result


# ---------------------------------------------------------------- retention
def run_retention(
    db: Session, now: datetime, lake_dir: str | os.PathLike | None = None
) -> int:
    """Delete old raw rows, but only for days with a Parquet partition and their 1h rollups."""
    now = services.as_utc(now)
    cutoff = now - timedelta(days=settings.raw_retention_days)
    hour_watermark = _watermark(db, "1h")
    deleted = 0

    for day in _raw_days_before(db, cutoff):
        path = partition_path(day, lake_dir)
        if not path.exists() or hour_watermark is None:
            continue
        # A partition missing rows (exported before the day was over) must not license deletes
        if _partition_rows(path) < _raw_count(db, day):
            continue
        start = _day_start(day)
        end = min(start + timedelta(days=1), cutoff)
        newest = db.scalar(
            select(func.max(models.Reading.ts)).where(
                models.Reading.ts >= start, models.Reading.ts < end
            )
        )
        # Rollups advance in order, so the watermark covering the newest hour covers the day
        if newest is None or floor_time(newest, 3600) > hour_watermark:
            continue
        result = db.execute(
            delete(models.Reading).where(models.Reading.ts >= start, models.Reading.ts < end)
        )
        deleted += result.rowcount or 0

    db.execute(
        delete(models.ReadingRollup).where(
            models.ReadingRollup.bucket == "1m",
            models.ReadingRollup.bucket_start < now - timedelta(days=ROLLUP_1M_RETENTION_DAYS),
        )
    )
    db.flush()
    return deleted


# ---------------------------------------------------------------- anomalies
async def detect_anomalies(db: Session, now: datetime) -> list[models.Event]:
    """Rolling z-score of the newest closed 1m average against the previous 24 h of 1m averages."""
    now = services.as_utc(now)
    current_minute = floor_time(now, 60)
    recent = db.scalars(
        select(models.ReadingRollup)
        .where(
            models.ReadingRollup.bucket == "1m",
            models.ReadingRollup.metric.in_(ANOMALY_METRICS),
            models.ReadingRollup.bucket_start >= current_minute - ANOMALY_MAX_AGE,
            models.ReadingRollup.bucket_start < current_minute,
        )
        .order_by(models.ReadingRollup.bucket_start)
    ).all()
    newest: dict[tuple[int, str], models.ReadingRollup] = {}
    for row in recent:
        newest[(row.device_id, row.metric)] = row  # ordered, so the last one wins

    events: list[models.Event] = []
    for key, row in newest.items():
        bucket_start = services.as_utc(row.bucket_start)
        if _anomaly_last_checked.get(key) == bucket_start:
            continue
        _anomaly_last_checked[key] = bucket_start

        device_id, metric = key
        baseline = db.scalars(
            select(models.ReadingRollup.avg).where(
                models.ReadingRollup.device_id == device_id,
                models.ReadingRollup.metric == metric,
                models.ReadingRollup.bucket == "1m",
                models.ReadingRollup.bucket_start >= bucket_start - timedelta(hours=24),
                models.ReadingRollup.bucket_start < bucket_start,
            )
        ).all()
        if len(baseline) < ANOMALY_MIN_BASELINE:
            continue
        mean = statistics.fmean(baseline)
        std = statistics.pstdev(baseline, mean)
        if std == 0:
            continue
        z = (row.avg - mean) / std
        if abs(z) <= settings.anomaly_z:
            continue

        last = _anomaly_last_event.get(key)
        if last is not None and now - last < ANOMALY_COOLDOWN:
            continue
        _anomaly_last_event[key] = now
        events.append(
            await services.log_event(
                db,
                type="anomaly",
                severity="warning",
                message=(
                    f"Bất thường: {ANOMALY_LABEL[metric]} {row.avg:.1f} "
                    f"(z={z:.1f}, TB 24h {mean:.1f})"
                ),
                device=db.get(models.Device, device_id),
            )
        )
    return events


def reset_state() -> None:
    """Forget scheduler and cooldown state (used by tests)."""
    global _last_minute, _last_daily
    _last_minute = None
    _last_daily = None
    _anomaly_last_event.clear()
    _anomaly_last_checked.clear()


# ---------------------------------------------------------------- scheduler
async def tick(db: Session, now: datetime | None = None) -> None:
    """Called every background tick; does real work only once a minute and once a day."""
    global _last_minute, _last_daily
    now = services.as_utc(now) or services.utcnow()

    minute = floor_time(now, 60)
    if minute != _last_minute:
        _last_minute = minute
        run_rollups(db, now)
        db.commit()
        await detect_anomalies(db, now)
        db.commit()

    today = now.date()
    if _last_daily != today and now.time() >= DAILY_JOB_AFTER:
        _last_daily = today
        exported = export_missing_days(db, now)
        deleted = run_retention(db, now)
        db.commit()
        if exported or deleted:
            _log(f"exported {len(exported)} day(s), deleted {deleted} raw reading(s)")


# ---------------------------------------------------------------- CLI
def main(argv: list[str] | None = None) -> None:
    from .database import Base, SessionLocal, engine

    parser = argparse.ArgumentParser(prog="python -m app.analytics")
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("export", help="export one UTC day to the Parquet lake")
    export.add_argument("--date", required=True, type=date.fromisoformat, help="YYYY-MM-DD (UTC)")
    export.add_argument("--force", action="store_true", help="overwrite an existing partition")
    commands.add_parser("rollup", help="run rollups up to now")
    args = parser.parse_args(argv)

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        if args.command == "export":
            path = export_day(db, args.date, force=args.force)
            if path is None:
                existing = partition_path(args.date)
                print(
                    f"skipped: {existing} already exists (use --force)"
                    if existing.exists()
                    else f"no readings on {args.date}"
                )
            else:
                rows = pq.ParquetFile(path).metadata.num_rows
                print(f"wrote {rows} rows to {path}")
        else:
            print(run_rollups(db, services.utcnow()))
            db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    main()
