from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import mqtt_bridge, schemas
from ..database import get_db

router = APIRouter(prefix="/api", tags=["live"])


@router.get("/live", response_model=schemas.LiveOut)
def get_live():
    """Cam bien moi nhat + che do + trang thai ket noi (giong /api/state ben Django)."""
    return mqtt_bridge.get_state()


@router.post("/mode", response_model=schemas.LiveOut)
async def set_mode(payload: schemas.ModeIn, db: Session = Depends(get_db)):
    """Chuyen che do tu dong / thu cong cho ESP32."""
    try:
        await mqtt_bridge.set_mode(db, payload.mode)
    except mqtt_bridge.BridgeError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)
    db.commit()
    return mqtt_bridge.get_state()


@router.post("/command")
async def send_command(payload: schemas.CommandIn, db: Session = Depends(get_db)):
    """Bat/tat den, quat, loa - chi dung duoc o che do thu cong."""
    try:
        await mqtt_bridge.manual_command(db, payload.device, payload.state)
    except mqtt_bridge.BridgeError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)
    db.commit()
    return {"ok": True}
