"""Nghiep vu dung chung: ghi telemetry, chay automation, dieu khien thiet bi."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models
from .bridge_devices import BRIDGED_CODES
from .realtime import manager

# Hen gio tat tu dong: {device_id: thoi diem phai tat}
# Vong lap nen trong main.py se quet dict nay moi giay.
auto_off_deadlines: dict[int, datetime] = {}

# Gia tri chuyen dong lan truoc cua tung thiet bi, de chi bao su kien khi 0 -> 1
_last_motion: dict[int, float] = {}

OPERATORS = {
    "gt": lambda a, b: a > b,
    "gte": lambda a, b: a >= b,
    "lt": lambda a, b: a < b,
    "lte": lambda a, b: a <= b,
    "eq": lambda a, b: abs(a - b) < 1e-9,
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime | None) -> datetime | None:
    """SQLite tra ve datetime khong co timezone -> gan lai UTC cho dung."""
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def device_payload(device: models.Device) -> dict:
    return {
        "id": device.id,
        "code": device.code,
        "name": device.name,
        "kind": device.kind,
        "room": device.room,
        "online": device.online,
        "state": device.state,
        "auto_mode": device.auto_mode,
        "last_seen": as_utc(device.last_seen),
    }


def event_payload(event: models.Event) -> dict:
    return {
        "id": event.id,
        "device_id": event.device_id,
        "device_name": event.device.name if event.device else None,
        "type": event.type,
        "severity": event.severity,
        "message": event.message,
        "acknowledged": event.acknowledged,
        "ts": as_utc(event.ts),
    }


def get_device_by_code(db: Session, code: str) -> models.Device | None:
    return db.scalar(select(models.Device).where(models.Device.code == code))


def get_or_create_device(db: Session, code: str, kind: str = "sensor") -> models.Device:
    """Thiet bi la gui du lieu len se duoc tu dong dang ky (tien cho lan cam dau tien)."""
    device = get_device_by_code(db, code)
    if device is None:
        device = models.Device(code=code, name=code, kind=kind, room="Chua gan phong")
        db.add(device)
        db.flush()
    return device


async def log_event(
    db: Session,
    *,
    type: str,
    message: str,
    severity: str = "info",
    device: models.Device | None = None,
) -> models.Event:
    event = models.Event(
        device_id=device.id if device else None,
        type=type,
        severity=severity,
        message=message,
        ts=utcnow(),
    )
    db.add(event)
    db.flush()
    db.refresh(event)
    await manager.broadcast("event", event_payload(event))
    return event


async def set_device_state(
    db: Session,
    device: models.Device,
    state: bool,
    *,
    source: str = "manual",
    auto_off_seconds: int = 0,
) -> None:
    """Doi trang thai actuator, tao lenh cho ESP32 va bao cho dashboard."""
    changed = device.state != state
    device.state = state
    db.add(models.Command(device_id=device.id, action="on" if state else "off", source=source))

    if state and auto_off_seconds > 0:
        auto_off_deadlines[device.id] = utcnow() + timedelta(seconds=auto_off_seconds)
    else:
        auto_off_deadlines.pop(device.id, None)

    db.flush()
    if changed:
        await manager.broadcast("device", device_payload(device))


async def evaluate_automations(db: Session, source: models.Device, metric: str, value: float) -> None:
    """Chay cac luat khop voi metric vua nhan duoc."""
    rules = db.scalars(
        select(models.Automation).where(
            models.Automation.enabled.is_(True),
            models.Automation.metric == metric,
        )
    ).all()

    now = utcnow()
    for rule in rules:
        if rule.source_device_id is not None and rule.source_device_id != source.id:
            continue
        compare = OPERATORS.get(rule.operator)
        if compare is None or not compare(value, rule.threshold):
            continue

        target = db.get(models.Device, rule.target_device_id)
        if target is None or not target.auto_mode or target.code in BRIDGED_CODES:
            continue  # thiet bi MQTT do ESP32 tu dieu khien

        desired = rule.action == "on"

        # Cam bien con kich hoat lien tuc -> gia han thoi gian tat tu dong
        if desired and target.state and rule.auto_off_seconds > 0:
            auto_off_deadlines[target.id] = now + timedelta(seconds=rule.auto_off_seconds)

        last = as_utc(rule.last_triggered)
        if last and (now - last).total_seconds() < rule.cooldown_seconds:
            continue
        if target.state == desired:
            rule.last_triggered = now
            continue

        rule.last_triggered = now
        await set_device_state(
            db,
            target,
            desired,
            source="automation",
            auto_off_seconds=rule.auto_off_seconds if desired else 0,
        )
        verb = "bat" if desired else "tat"
        await log_event(
            db,
            type="automation",
            severity="info",
            message=f"Luat [{rule.name}] da {verb} {target.name} ({metric}={value:g})",
            device=target,
        )
        await manager.broadcast("automation", {"id": rule.id, "last_triggered": now})


async def handle_fall(db: Session, device: models.Device, message: str | None = None) -> models.Event:
    """Phat hien nga: ghi canh bao nghiem trong va hu coi bao neu co."""
    event = await log_event(
        db,
        type="fall_detected",
        severity="critical",
        message=message or f"Phat hien nga tai {device.room} ({device.name})",
        device=device,
    )
    for alarm in db.scalars(select(models.Device).where(models.Device.kind == "alarm")).all():
        if alarm.auto_mode and alarm.code not in BRIDGED_CODES:
            await set_device_state(db, alarm, True, source="automation", auto_off_seconds=30)
    return event


async def record_telemetry(
    db: Session,
    device: models.Device,
    metrics: dict[str, float],
    ts: datetime | None = None,
) -> list[models.Reading]:
    """Luu cac gia tri cam bien, sinh su kien can thiet va chay automation."""
    stamp = as_utc(ts) or utcnow()
    was_offline = not device.online
    device.online = True
    device.last_seen = stamp

    readings: list[models.Reading] = []
    for metric, raw_value in metrics.items():
        value = float(raw_value)
        reading = models.Reading(device_id=device.id, metric=metric, value=value, ts=stamp)
        db.add(reading)
        readings.append(reading)

    db.flush()

    if was_offline:
        await manager.broadcast("device", device_payload(device))
        await log_event(db, type="device_online", message=f"{device.name} da ket noi", device=device)

    for reading in readings:
        await manager.broadcast(
            "reading",
            {
                "device_id": device.id,
                "device_code": device.code,
                "metric": reading.metric,
                "value": reading.value,
                "ts": stamp,
            },
        )

        # Chuyen dong: chi ghi su kien khi chuyen tu khong -> co
        if reading.metric == "motion":
            previous = _last_motion.get(device.id, 0.0)
            if reading.value >= 1 and previous < 1:
                await log_event(
                    db,
                    type="motion",
                    message=f"Phat hien chuyen dong tai {device.room}",
                    device=device,
                )
            _last_motion[device.id] = reading.value

        # Nga: firmware co the gui metric "fall" = 1 thay vi goi endpoint su kien
        if reading.metric == "fall" and reading.value >= 1:
            await handle_fall(db, device)

        await evaluate_automations(db, device, reading.metric, reading.value)

    return readings


async def run_auto_off(db: Session) -> None:
    """Tat cac thiet bi da het thoi gian hen gio (goi dinh ky tu background task)."""
    now = utcnow()
    expired = [device_id for device_id, deadline in auto_off_deadlines.items() if deadline <= now]
    for device_id in expired:
        auto_off_deadlines.pop(device_id, None)
        device = db.get(models.Device, device_id)
        if device is None or not device.state:
            continue
        await set_device_state(db, device, False, source="automation")
        await log_event(
            db,
            type="automation",
            message=f"{device.name} tu dong tat sau khi het thoi gian cho",
            device=device,
        )


async def mark_offline_devices(db: Session, timeout_seconds: int = 60) -> None:
    """Thiet bi khong gui du lieu qua timeout_seconds bi coi la mat ket noi."""
    limit = utcnow() - timedelta(seconds=timeout_seconds)
    for device in db.scalars(select(models.Device).where(models.Device.online.is_(True))).all():
        last_seen = as_utc(device.last_seen)
        if last_seen is None or last_seen < limit:
            device.online = False
            db.flush()
            await manager.broadcast("device", device_payload(device))
            await log_event(
                db,
                type="device_offline",
                severity="warning",
                message=f"{device.name} mat ket noi",
                device=device,
            )
