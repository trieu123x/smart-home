from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db

router = APIRouter(prefix="/api/events", tags=["events"])


def _to_out(event: models.Event) -> schemas.EventOut:
    data = schemas.EventOut.model_validate(event)
    data.device_name = event.device.name if event.device else None
    return data


@router.get("", response_model=list[schemas.EventOut])
def list_events(
    db: Session = Depends(get_db),
    limit: int = Query(default=50, le=500),
    type: str | None = None,
    severity: str | None = None,
    only_unacknowledged: bool = False,
):
    query = select(models.Event).order_by(models.Event.ts.desc()).limit(limit)
    if type:
        query = query.where(models.Event.type == type)
    if severity:
        query = query.where(models.Event.severity == severity)
    if only_unacknowledged:
        query = query.where(models.Event.acknowledged.is_(False))
    return [_to_out(event) for event in db.scalars(query).all()]


@router.post("/{event_id}/ack", response_model=schemas.EventOut)
def acknowledge_event(event_id: int, db: Session = Depends(get_db)):
    event = db.get(models.Event, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Khong tim thay su kien")
    event.acknowledged = True
    db.commit()
    db.refresh(event)
    return _to_out(event)


@router.post("/ack-all")
def acknowledge_all(db: Session = Depends(get_db)):
    events = db.scalars(select(models.Event).where(models.Event.acknowledged.is_(False))).all()
    for event in events:
        event.acknowledged = True
    db.commit()
    return {"acknowledged": len(events)}


@router.delete("/{event_id}", status_code=204)
def delete_event(event_id: int, db: Session = Depends(get_db)):
    event = db.get(models.Event, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Khong tim thay su kien")
    db.delete(event)
    db.commit()

