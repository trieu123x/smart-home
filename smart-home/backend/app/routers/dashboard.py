import math
from datetime import timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import models, schemas, services
from ..database import get_db

router = APIRouter(prefix="/api", tags=["dashboard"])


def _latest_value(db: Session, metric: str) -> float | None:
    row = db.execute(
        select(models.Reading.value)
        .where(models.Reading.metric == metric)
        .order_by(models.Reading.ts.desc())
        .limit(1)
    ).first()
    return float(row[0]) if row else None


@router.get("/summary", response_model=schemas.SummaryOut)
def get_summary(db: Session = Depends(get_db)):
    """So lieu tong hop cho hang the o dau dashboard."""
    since = services.utcnow() - timedelta(hours=24)

    devices_total = db.scalar(select(func.count(models.Device.id))) or 0
    devices_online = (
        db.scalar(select(func.count(models.Device.id)).where(models.Device.online.is_(True))) or 0
    )
    actuators_on = (
        db.scalar(
            select(func.count(models.Device.id)).where(
                models.Device.state.is_(True), models.Device.kind != "sensor"
            )
        )
        or 0
    )
    motion_24h = (
        db.scalar(
            select(func.count(models.Event.id)).where(
                models.Event.type == "motion", models.Event.ts >= since
            )
        )
        or 0
    )
    falls_24h = (
        db.scalar(
            select(func.count(models.Event.id)).where(
                models.Event.type == "fall_detected", models.Event.ts >= since
            )
        )
        or 0
    )
    unacked = (
        db.scalar(
            select(func.count(models.Event.id)).where(
                models.Event.acknowledged.is_(False),
                models.Event.severity.in_(["warning", "critical"]),
            )
        )
        or 0
    )

    last_fall_event = db.scalar(
        select(models.Event)
        .where(models.Event.type == "fall_detected")
        .order_by(models.Event.ts.desc())
        .limit(1)
    )
    last_fall = None
    if last_fall_event is not None:
        last_fall = schemas.EventOut.model_validate(last_fall_event)
        last_fall.device_name = last_fall_event.device.name if last_fall_event.device else None

    return schemas.SummaryOut(
        devices_total=devices_total,
        devices_online=devices_online,
        actuators_on=actuators_on,
        temperature=_latest_value(db, "temperature"),
        humidity=_latest_value(db, "humidity"),
        lux=_latest_value(db, "lux"),
        motion_last_24h=motion_24h,
        falls_last_24h=falls_24h,
        unacknowledged_alerts=unacked,
        last_fall=last_fall,
    )


@router.get("/readings", response_model=list[schemas.ReadingOut])
def list_readings(
    db: Session = Depends(get_db),
    metric: str | None = None,
    device_id: int | None = None,
    hours: int = Query(default=6, ge=1, le=168),
    limit: int = Query(default=300, le=2000),
):
    since = services.utcnow() - timedelta(hours=hours)
    query = (
        select(models.Reading)
        .where(models.Reading.ts >= since)
        .order_by(models.Reading.ts.desc())
        .limit(limit)
    )
    if metric:
        query = query.where(models.Reading.metric == metric)
    if device_id:
        query = query.where(models.Reading.device_id == device_id)
    rows = db.scalars(query).all()
    return list(reversed(rows))


@router.get("/series", response_model=list[schemas.MetricSeries])
def get_series(
    db: Session = Depends(get_db),
    metrics: str = Query(default="temperature,humidity"),
    hours: int = Query(default=6, ge=1, le=168),
    points: int = Query(default=60, ge=10, le=500),
):
    """Chuoi du lieu da lam thua cho bieu do (lay deu <points> diem tren ca khoang thoi gian).

    Up to 6 h reads raw rows, up to 48 h reads 1m rollup averages, longer ranges 1h rollups.
    """
    since = services.utcnow() - timedelta(hours=hours)
    result: list[schemas.MetricSeries] = []

    for metric in [m.strip() for m in metrics.split(",") if m.strip()]:
        if hours <= 6:
            query = select(models.Reading.ts, models.Reading.value).where(
                models.Reading.metric == metric, models.Reading.ts >= since
            ).order_by(models.Reading.ts)
        else:
            rollup = models.ReadingRollup
            query = (
                select(rollup.bucket_start, rollup.avg)
                .where(
                    rollup.metric == metric,
                    rollup.bucket == ("1m" if hours <= 48 else "1h"),
                    rollup.bucket_start >= since,
                )
                .order_by(rollup.bucket_start)
            )
        rows = db.execute(query).all()
        step = max(1, math.ceil(len(rows) / points))
        sampled = rows[::step]
        result.append(
            schemas.MetricSeries(
                metric=metric,
                points=[
                    schemas.MetricPoint(ts=services.as_utc(ts), value=float(value))
                    for ts, value in sampled
                ],
            )
        )
    return result


@router.get("/activity")
def get_activity(db: Session = Depends(get_db), hours: int = Query(default=24, ge=1, le=168)):
    """Dem su kien theo tung gio -> bieu do cot hoat dong trong nha."""
    since = services.utcnow() - timedelta(hours=hours)
    rows = db.execute(
        select(
            func.strftime("%Y-%m-%dT%H:00", models.Event.ts).label("bucket"),
            models.Event.type,
            func.count(models.Event.id),
        )
        .where(models.Event.ts >= since)
        .group_by("bucket", models.Event.type)
        .order_by("bucket")
    ).all()

    buckets: dict[str, dict[str, int]] = {}
    for bucket, event_type, count in rows:
        entry = buckets.setdefault(bucket, {"hour": bucket, "motion": 0, "fall": 0, "automation": 0})
        if event_type == "motion":
            entry["motion"] += count
        elif event_type == "fall_detected":
            entry["fall"] += count
        elif event_type == "automation":
            entry["automation"] += count
    return list(buckets.values())
