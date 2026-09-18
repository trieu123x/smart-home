from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db

router = APIRouter(prefix="/api/automations", tags=["automations"])


def _to_out(rule: models.Automation) -> schemas.AutomationOut:
    data = schemas.AutomationOut.model_validate(rule)
    data.target_device_name = rule.target_device.name if rule.target_device else None
    data.source_device_name = rule.source_device.name if rule.source_device else None
    return data


@router.get("", response_model=list[schemas.AutomationOut])
def list_automations(db: Session = Depends(get_db)):
    rules = db.scalars(select(models.Automation).order_by(models.Automation.id)).all()
    return [_to_out(rule) for rule in rules]


@router.post("", response_model=schemas.AutomationOut, status_code=201)
def create_automation(payload: schemas.AutomationCreate, db: Session = Depends(get_db)):
    if db.get(models.Device, payload.target_device_id) is None:
        raise HTTPException(status_code=400, detail="Thiet bi dich khong ton tai")
    if payload.source_device_id and db.get(models.Device, payload.source_device_id) is None:
        raise HTTPException(status_code=400, detail="Thiet bi nguon khong ton tai")
    rule = models.Automation(**payload.model_dump())
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return _to_out(rule)


@router.patch("/{rule_id}", response_model=schemas.AutomationOut)
def update_automation(
    rule_id: int, payload: schemas.AutomationUpdate, db: Session = Depends(get_db)
):
    rule = db.get(models.Automation, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Khong tim thay luat")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(rule, field, value)
    db.commit()
    db.refresh(rule)
    return _to_out(rule)


@router.delete("/{rule_id}", status_code=204)
def delete_automation(rule_id: int, db: Session = Depends(get_db)):
    rule = db.get(models.Automation, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Khong tim thay luat")
    db.delete(rule)
    db.commit()
