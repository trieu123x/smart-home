from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import schemas, services
from ..database import get_db
from ..security import require_device_key

router = APIRouter(prefix="/api/ingest", tags=["ingest"], dependencies=[Depends(require_device_key)])


@router.post("/telemetry", status_code=202)
async def ingest_telemetry(payload: schemas.TelemetryIn, db: Session = Depends(get_db)):
    """ESP32 day so lieu cam bien len day.

    Vi du body:
        {"device_code": "esp32-phongkhach", "metrics": {"temperature": 31.2, "motion": 1}}
    """
    device = services.get_or_create_device(db, payload.device_code)
    readings = await services.record_telemetry(db, device, payload.metrics, payload.ts)
    db.commit()
    return {"accepted": len(readings), "device_id": device.id}


@router.post("/event", status_code=202)
async def ingest_event(payload: schemas.EventIn, db: Session = Depends(get_db)):
    """ESP32 bao mot su kien roi rac, vi du nga duoc phat hien ngay tren MPU6050."""
    device = None
    if payload.device_code:
        device = services.get_or_create_device(db, payload.device_code)
        device.online = True
        device.last_seen = services.utcnow()

    if payload.type == "fall_detected":
        if device is None:
            raise HTTPException(status_code=400, detail="Su kien nga phai kem device_code")
        event = await services.handle_fall(db, device, payload.message)
    else:
        event = await services.log_event(
            db,
            type=payload.type,
            severity=payload.severity,
            message=payload.message,
            device=device,
        )
    db.commit()
    return {"id": event.id}
