from datetime import date, datetime, timezone
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field


def _ensure_utc(value: datetime) -> datetime:
    """SQLite luu datetime khong kem timezone -> gan lai UTC truoc khi tra ve JSON."""
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


UtcDatetime = Annotated[datetime, AfterValidator(_ensure_utc)]


DeviceKind = Literal["sensor", "fan", "light", "alarm"]
Operator = Literal["gt", "gte", "lt", "lte", "eq"]
Action = Literal["on", "off"]


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------- Device ----------
class DeviceCreate(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    name: str
    kind: DeviceKind
    room: str = "Chung"


class DeviceUpdate(BaseModel):
    name: str | None = None
    room: str | None = None
    auto_mode: bool | None = None


class DeviceOut(ORMModel):
    id: int
    code: str
    name: str
    kind: str
    room: str
    online: bool
    state: bool
    auto_mode: bool
    last_seen: UtcDatetime | None
    created_at: UtcDatetime


class DeviceToggle(BaseModel):
    state: bool


# ---------- Reading ----------
class ReadingIn(BaseModel):
    metric: str
    value: float
    ts: UtcDatetime | None = None


class ReadingOut(ORMModel):
    id: int
    device_id: int
    metric: str
    value: float
    ts: UtcDatetime


class TelemetryIn(BaseModel):
    """Payload ESP32 gui len: mot lan doc nhieu cam bien cung luc."""

    device_code: str
    # vi du {"temperature": 30.4, "humidity": 68, "motion": 1, "lux": 120}
    metrics: dict[str, float]
    ts: UtcDatetime | None = None


# ---------- Event ----------
class EventIn(BaseModel):
    device_code: str | None = None
    type: str
    severity: Literal["info", "warning", "critical"] = "info"
    message: str
    ts: UtcDatetime | None = None


class EventOut(ORMModel):
    id: int
    device_id: int | None
    type: str
    severity: str
    message: str
    acknowledged: bool
    ts: UtcDatetime
    device_name: str | None = None


# ---------- Automation ----------
class AutomationCreate(BaseModel):
    name: str
    metric: str
    operator: Operator = "gt"
    threshold: float
    target_device_id: int
    source_device_id: int | None = None
    action: Action = "on"
    auto_off_seconds: int = 0
    cooldown_seconds: int = 10
    enabled: bool = True


class AutomationUpdate(BaseModel):
    name: str | None = None
    metric: str | None = None
    operator: Operator | None = None
    threshold: float | None = None
    target_device_id: int | None = None
    source_device_id: int | None = None
    action: Action | None = None
    auto_off_seconds: int | None = None
    cooldown_seconds: int | None = None
    enabled: bool | None = None


class AutomationOut(ORMModel):
    id: int
    name: str
    enabled: bool
    metric: str
    operator: str
    threshold: float
    source_device_id: int | None
    target_device_id: int
    action: str
    auto_off_seconds: int
    cooldown_seconds: int
    last_triggered: UtcDatetime | None
    target_device_name: str | None = None
    source_device_name: str | None = None


# ---------- Tong hop cho dashboard ----------
class MetricPoint(BaseModel):
    ts: UtcDatetime
    value: float


class MetricSeries(BaseModel):
    metric: str
    points: list[MetricPoint]


class SummaryOut(BaseModel):
    devices_total: int
    devices_online: int
    actuators_on: int
    temperature: float | None
    humidity: float | None
    lux: float | None
    motion_last_24h: int
    falls_last_24h: int
    unacknowledged_alerts: int
    last_fall: EventOut | None


class CommandOut(ORMModel):
    id: int
    action: str
    source: str
    created_at: UtcDatetime


# ---------- Trang thai truc tiep tu ESP32 qua MQTT ----------
class LiveOut(BaseModel):
    """Giong /api/state cua ban Django: cam bien moi nhat + che do + trang thai ket noi."""

    sensors: dict[str, Any]
    mode: Literal["auto", "manual"]
    esp_online: bool
    broker_ok: bool
    age: float | None = None


class ModeIn(BaseModel):
    mode: Literal["auto", "manual"]


class CommandIn(BaseModel):
    device: Literal["light", "fan", "buzzer"]
    state: bool


# ---------- Analytics ----------
class RollupPoint(BaseModel):
    bucket_start: UtcDatetime
    min: float
    max: float
    avg: float
    count: int


class MetricStats(BaseModel):
    metric: str
    min: float
    max: float
    avg: float
    count: int
    anomalies: int


class LakePartition(BaseModel):
    date: date
    rows: int
    bytes: int


# ---------- Auth ----------
class LoginIn(BaseModel):
    password: str = Field(max_length=256)


class LoginOut(BaseModel):
    token: str
    expires_at: UtcDatetime
