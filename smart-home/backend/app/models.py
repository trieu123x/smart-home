from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Device(Base):
    """Mot thiet bi vat ly: cam bien hoac co cau chap hanh (quat, den)."""

    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Ma do firmware ESP32 gui len, vi du "esp32-livingroom-01"
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    # sensor | fan | light | alarm
    kind: Mapped[str] = mapped_column(String(32))
    room: Mapped[str] = mapped_column(String(64), default="Chung")
    online: Mapped[bool] = mapped_column(Boolean, default=False)
    # Trang thai bat/tat cua actuator (quat, den). Sensor luon False.
    state: Mapped[bool] = mapped_column(Boolean, default=False)
    # True = actuator do automation dieu khien, False = nguoi dung tu bat/tat
    auto_mode: Mapped[bool] = mapped_column(Boolean, default=True)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    readings: Mapped[list["Reading"]] = relationship(back_populates="device", cascade="all, delete-orphan")
    events: Mapped[list["Event"]] = relationship(back_populates="device", cascade="all, delete-orphan")


class Reading(Base):
    """Mot diem du lieu cam bien (temperature, humidity, lux, motion, fall_score...)."""

    __tablename__ = "readings"

    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), index=True)
    metric: Mapped[str] = mapped_column(String(32), index=True)
    value: Mapped[float] = mapped_column(Float)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

    device: Mapped[Device] = relationship(back_populates="readings")


class Event(Base):
    """Su kien dang ke: phat hien nga, phat hien chuyen dong, automation chay..."""

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[int | None] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"), nullable=True, index=True
    )
    # fall_detected | motion | automation | device_online | device_offline | manual
    type: Mapped[str] = mapped_column(String(32), index=True)
    # info | warning | critical
    severity: Mapped[str] = mapped_column(String(16), default="info", index=True)
    message: Mapped[str] = mapped_column(Text)
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

    device: Mapped[Device | None] = relationship(back_populates="events")


class Automation(Base):
    """Luat tu dong: khi <metric> <op> <threshold> thi bat/tat thiet bi dich."""

    __tablename__ = "automations"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # Cam bien nguon; None = bat ky cam bien nao gui metric nay
    source_device_id: Mapped[int | None] = mapped_column(
        ForeignKey("devices.id", ondelete="SET NULL"), nullable=True
    )
    metric: Mapped[str] = mapped_column(String(32))
    # gt | gte | lt | lte | eq
    operator: Mapped[str] = mapped_column(String(8), default="gt")
    threshold: Mapped[float] = mapped_column(Float)
    target_device_id: Mapped[int] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"))
    # on | off
    action: Mapped[str] = mapped_column(String(8), default="on")
    # Tat tu dong sau N giay (0 = khong tu tat). Dung cho den bat theo chuyen dong.
    auto_off_seconds: Mapped[int] = mapped_column(Integer, default=0)
    # Khoang cho toi thieu giua 2 lan kich hoat, tranh nhay lien tuc
    cooldown_seconds: Mapped[int] = mapped_column(Integer, default=10)
    last_triggered: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    source_device: Mapped[Device | None] = relationship(foreign_keys=[source_device_id])
    target_device: Mapped[Device] = relationship(foreign_keys=[target_device_id])


class Command(Base):
    """Lenh cho ESP32. Firmware goi GET /api/devices/{code}/commands de lay ve."""

    __tablename__ = "commands"

    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), index=True)
    action: Mapped[str] = mapped_column(String(16))  # on | off
    source: Mapped[str] = mapped_column(String(32), default="manual")  # manual | automation
    delivered: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    device: Mapped[Device] = relationship()
