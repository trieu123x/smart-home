"""Tao san thiet bi, luat tu dong va it du lieu mau cho lan chay dau tien."""

import math
import random
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import models
from .services import utcnow

DEVICES = [
    ("esp32-phongkhach", "Cam bien phong khach", "sensor", "Phong khach"),
    ("esp32-phongngu", "Cam bien phong ngu", "sensor", "Phong ngu"),
    ("esp32-nhatam", "Cam bien nga nha tam", "sensor", "Nha tam"),
    ("fan-phongkhach", "Quat phong khach", "fan", "Phong khach"),
    ("light-phongkhach", "Den phong khach", "light", "Phong khach"),
    ("light-hanhlang", "Den hanh lang", "light", "Hanh lang"),
    ("alarm-trungtam", "Coi bao trung tam", "alarm", "Phong khach"),
]

AUTOMATIONS = [
    {
        "name": "Bat quat khi nong tren 30 do",
        "metric": "temperature",
        "operator": "gt",
        "threshold": 30.0,
        "target_code": "fan-phongkhach",
        "action": "on",
        "auto_off_seconds": 0,
        "cooldown_seconds": 60,
    },
    {
        "name": "Tat quat khi duoi 27 do",
        "metric": "temperature",
        "operator": "lt",
        "threshold": 27.0,
        "target_code": "fan-phongkhach",
        "action": "off",
        "auto_off_seconds": 0,
        "cooldown_seconds": 60,
    },
    {
        "name": "Bat den khi co chuyen dong",
        "metric": "motion",
        "operator": "gte",
        "threshold": 1.0,
        "target_code": "light-phongkhach",
        "action": "on",
        "auto_off_seconds": 30,
        "cooldown_seconds": 5,
    },
    {
        "name": "Bat den hanh lang khi troi toi va co nguoi",
        "metric": "lux",
        "operator": "lt",
        "threshold": 80.0,
        "target_code": "light-hanhlang",
        "action": "on",
        "auto_off_seconds": 60,
        "cooldown_seconds": 10,
    },
]


def seed_if_empty(db: Session) -> None:
    if db.scalar(select(func.count(models.Device.id))):
        return

    devices: dict[str, models.Device] = {}
    for code, name, kind, room in DEVICES:
        device = models.Device(code=code, name=name, kind=kind, room=room)
        db.add(device)
        devices[code] = device
    db.flush()

    for rule in AUTOMATIONS:
        db.add(
            models.Automation(
                name=rule["name"],
                metric=rule["metric"],
                operator=rule["operator"],
                threshold=rule["threshold"],
                target_device_id=devices[rule["target_code"]].id,
                action=rule["action"],
                auto_off_seconds=rule["auto_off_seconds"],
                cooldown_seconds=rule["cooldown_seconds"],
            )
        )

    _seed_history(db, devices)
    db.commit()


def _seed_history(db: Session, devices: dict[str, models.Device]) -> None:
    """Sinh 12 gio du lieu gia de bieu do khong trong khi chua cam thiet bi that."""
    sensor = devices["esp32-phongkhach"]
    now = utcnow()
    for index in range(144):  # 12 gio, moi 5 phut
        ts = now - timedelta(minutes=5 * (143 - index))
        phase = index / 144 * math.pi * 2
        temperature = 28.5 + 3.2 * math.sin(phase) + random.uniform(-0.3, 0.3)
        humidity = 65 + 8 * math.cos(phase) + random.uniform(-1.5, 1.5)
        lux = max(0.0, 220 + 200 * math.sin(phase - 1) + random.uniform(-20, 20))
        db.add_all(
            [
                models.Reading(device_id=sensor.id, metric="temperature", value=round(temperature, 2), ts=ts),
                models.Reading(device_id=sensor.id, metric="humidity", value=round(humidity, 1), ts=ts),
                models.Reading(device_id=sensor.id, metric="lux", value=round(lux, 1), ts=ts),
            ]
        )
        if random.random() < 0.18:
            db.add(models.Reading(device_id=sensor.id, metric="motion", value=1, ts=ts))
            db.add(
                models.Event(
                    device_id=sensor.id,
                    type="motion",
                    severity="info",
                    message=f"Phat hien chuyen dong tai {sensor.room}",
                    ts=ts,
                )
            )

    db.add(
        models.Event(
            device_id=devices["esp32-nhatam"].id,
            type="fall_detected",
            severity="critical",
            message="Phat hien nga tai Nha tam (du lieu mau)",
            ts=now - timedelta(hours=5, minutes=12),
        )
    )
