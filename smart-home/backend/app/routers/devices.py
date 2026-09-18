from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models, schemas, services
from ..database import get_db
from ..security import require_device_key

router = APIRouter(prefix="/api/devices", tags=["devices"])


@router.get("", response_model=list[schemas.DeviceOut])
def list_devices(db: Session = Depends(get_db), kind: str | None = None, room: str | None = None):
    query = select(models.Device).order_by(models.Device.kind, models.Device.name)
    if kind:
        query = query.where(models.Device.kind == kind)
    if room:
        query = query.where(models.Device.room == room)
    return db.scalars(query).all()


@router.post("", response_model=schemas.DeviceOut, status_code=201)
def create_device(payload: schemas.DeviceCreate, db: Session = Depends(get_db)):
    if services.get_device_by_code(db, payload.code):
        raise HTTPException(status_code=409, detail="Ma thiet bi da ton tai")
    device = models.Device(**payload.model_dump())
    db.add(device)
    db.commit()
    db.refresh(device)
    return device


@router.get("/{device_id}", response_model=schemas.DeviceOut)
def get_device(device_id: int, db: Session = Depends(get_db)):
    device = db.get(models.Device, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="Khong tim thay thiet bi")
    return device


@router.patch("/{device_id}", response_model=schemas.DeviceOut)
def update_device(device_id: int, payload: schemas.DeviceUpdate, db: Session = Depends(get_db)):
    device = db.get(models.Device, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="Khong tim thay thiet bi")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(device, field, value)
    db.commit()
    db.refresh(device)
    return device


@router.delete("/{device_id}", status_code=204)
def delete_device(device_id: int, db: Session = Depends(get_db)):
    device = db.get(models.Device, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="Khong tim thay thiet bi")
    db.delete(device)
    db.commit()


@router.post("/{device_id}/toggle", response_model=schemas.DeviceOut)
async def toggle_device(
    device_id: int, payload: schemas.DeviceToggle, db: Session = Depends(get_db)
):
    """Nguoi dung bat/tat thu cong tu dashboard."""
    device = db.get(models.Device, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="Khong tim thay thiet bi")
    if device.kind == "sensor":
        raise HTTPException(status_code=400, detail="Khong the bat/tat mot cam bien")

    await services.set_device_state(db, device, payload.state, source="manual")
    verb = "bat" if payload.state else "tat"
    await services.log_event(
        db,
        type="manual",
        message=f"Nguoi dung {verb} {device.name}",
        device=device,
    )
    db.commit()
    db.refresh(device)
    return device


@router.get("/{code}/commands", response_model=list[schemas.CommandOut])
def pull_commands(
    code: str,
    db: Session = Depends(get_db),
    _: None = Depends(require_device_key),
):
    """ESP32 goi dinh ky de lay lenh moi (bat/tat relay) roi danh dau da nhan."""
    device = services.get_device_by_code(db, code)
    if device is None:
        raise HTTPException(status_code=404, detail="Khong tim thay thiet bi")

    commands = db.scalars(
        select(models.Command)
        .where(models.Command.device_id == device.id, models.Command.delivered.is_(False))
        .order_by(models.Command.created_at)
    ).all()
    for command in commands:
        command.delivered = True
    db.commit()
    return commands
