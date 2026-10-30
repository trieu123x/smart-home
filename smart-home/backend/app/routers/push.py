"""Authenticated push registrations for the shared-password Smart Home dashboard."""
import time
from collections import defaultdict, deque

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models
from ..config import settings
from ..database import get_db
from ..push_notify import enabled, send_push_all, valid_push_endpoint

router = APIRouter(prefix="/api/push", tags=["web push"])
_test_times = defaultdict(deque)


class BrowserKeys(BaseModel):
    auth: str = Field(min_length=10, max_length=512)
    p256dh: str = Field(min_length=32, max_length=512)


class BrowserSubscription(BaseModel):
    endpoint: str = Field(min_length=20, max_length=4096)
    keys: BrowserKeys


@router.get("/public-key")
def public_key():
    if not enabled():
        raise HTTPException(503, "Chưa cấu hình VAPID trong backend/.env")
    return {"publicKey": settings.vapid_public_key}


@router.post("/subscribe", status_code=201)
def subscribe(payload: BrowserSubscription, db: Session = Depends(get_db)):
    if not enabled():
        raise HTTPException(503, "Chưa cấu hình VAPID")
    if not valid_push_endpoint(payload.endpoint):
        raise HTTPException(422, "Push endpoint không hợp lệ")
    record = db.scalar(select(models.PushSubscription).where(models.PushSubscription.endpoint == payload.endpoint))
    if record is None:
        record = models.PushSubscription(endpoint=payload.endpoint,
                                         p256dh=payload.keys.p256dh, auth=payload.keys.auth)
        db.add(record)
    else:
        record.p256dh = payload.keys.p256dh
        record.auth = payload.keys.auth
    db.commit()
    return {"ok": True}


@router.post("/unsubscribe")
def unsubscribe(payload: BrowserSubscription, db: Session = Depends(get_db)):
    db.query(models.PushSubscription).filter(models.PushSubscription.endpoint == payload.endpoint).delete()
    db.commit()
    return {"ok": True}


@router.post("/test")
async def test_push(request: Request):
    # Small rate limit: avoid accidental notification floods.
    key = (request.cookies.get("smarthome_session") or "")[-32:]
    q = _test_times[key]
    now = time.monotonic()
    while q and now - q[0] > 60:
        q.popleft()
    if len(q) >= 3:
        raise HTTPException(429, "Chỉ kiểm tra tối đa 3 lần mỗi phút")
    q.append(now)
    return await send_push_all("SMART HOME - KIỂM TRA", "Đã kết nối thông báo trên điện thoại.",
                               tag="smart-home-test")
