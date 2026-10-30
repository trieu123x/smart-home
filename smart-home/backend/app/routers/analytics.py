from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import analytics, models, schemas, services
from ..database import get_db

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.get("/rollups", response_model=list[schemas.RollupPoint])
def get_rollups(
    metric: str,
    db: Session = Depends(get_db),
    bucket: Literal["1m", "1h"] = "1h",
    hours: int = Query(default=168, ge=1, le=720),
):
    """Min/avg/max per bucket, merged across devices (avg weighted by count)."""
    rollup = models.ReadingRollup
    since = services.utcnow() - timedelta(hours=hours)
    total = func.sum(rollup.count)
    rows = db.execute(
        select(
            rollup.bucket_start,
            func.min(rollup.min),
            func.max(rollup.max),
            func.sum(rollup.avg * rollup.count) / total,
            total,
        )
        .where(rollup.metric == metric, rollup.bucket == bucket, rollup.bucket_start >= since)
        .group_by(rollup.bucket_start)
        .order_by(rollup.bucket_start)
    ).all()
    return [
        schemas.RollupPoint(bucket_start=start, min=low, max=high, avg=mean, count=count)
        for start, low, high, mean, count in rows
    ]


@router.get("/stats", response_model=list[schemas.MetricStats])
def get_stats(db: Session = Depends(get_db), hours: int = Query(default=24, ge=1, le=168)):
    """Per-metric min/max/avg/count over raw readings, plus anomaly events in the window."""
    since = services.utcnow() - timedelta(hours=hours)
    rows = db.execute(
        select(
            models.Reading.metric,
            func.min(models.Reading.value),
            func.max(models.Reading.value),
            func.avg(models.Reading.value),
            func.count(models.Reading.id),
        )
        .where(models.Reading.ts >= since)
        .group_by(models.Reading.metric)
        .order_by(models.Reading.metric)
    ).all()

    # Events carry no metric column, so match on the label in the anomaly message
    messages = db.scalars(
        select(models.Event.message).where(
            models.Event.type == "anomaly", models.Event.ts >= since
        )
    ).all()
    result = []
    for metric, low, high, mean, count in rows:
        label = analytics.ANOMALY_LABEL.get(metric)
        prefix = f"Bất thường: {label} " if label else None
        anomalies = sum(1 for message in messages if prefix and message.startswith(prefix))
        result.append(
            schemas.MetricStats(
                metric=metric, min=low, max=high, avg=mean, count=count, anomalies=anomalies
            )
        )
    return result


@router.get("/lake", response_model=list[schemas.LakePartition])
def get_lake():
    """Parquet partitions in the local data lake, newest first."""
    return analytics.lake_partitions()
