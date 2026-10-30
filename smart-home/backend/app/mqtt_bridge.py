"""Cau noi MQTT <-> FastAPI, dung CUNG giao thuc voi ban Django (firmware ESP32 khong can sua).

Topic (prefix mac dinh `ptit_sh_k7x2q9/home/`):
  <prefix>sensors     ESP32 -> server : JSON {ldr, dark, temp, hum, gas, gas_base, gas_alarm,
                                              motion, mode, light, fan, buzzer}
  <prefix>status      ESP32 -> server : "online" / "offline" (Last Will)
  <prefix>mode        hai chieu, retained : "auto" / "manual"
  <prefix>cmd/<dev>   server -> ESP32 : "ON" / "OFF" (dev = light | fan | buzzer)

Che do AUTO: ESP32 tu chay logic (nhu code C++ hien tai), server chi hien thi.
Che do MANUAL: ESP32 chi gui cam bien, thiet bi chi doi khi server gui lenh cmd/<dev>.

Du lieu di qua 2 duong:
  * truc tiep : WebSocket kenh "live" (moi ban tin sensors) cho giao dien thoi gian thuc
  * luu tru   : Reading / Event / Device trong SQLite (thua, moi MQTT_HISTORY_SECONDS giay)
"""

import asyncio
import json
import threading
import time
import uuid
from typing import Any

import paho.mqtt.client as mqtt
from sqlalchemy.orm import Session

from . import cloud_sink, models, services
from .bridge_devices import ACTUATORS, ROOM, SENSOR_CODE, SENSOR_NAME
from .config import settings
from .database import SessionLocal
from .realtime import manager

PREFIX = settings.mqtt_topic_prefix
T_SENSORS = PREFIX + "sensors"
T_STATUS = PREFIX + "status"
T_MODE = PREFIX + "mode"
T_CMD = PREFIX + "cmd/"

# khoa trong JSON cam bien -> ten metric luu trong bang readings
METRIC_KEYS = {"temp": "temperature", "hum": "humidity", "ldr": "ldr", "gas": "gas"}

_lock = threading.Lock()
_state: dict[str, Any] = {
    "sensors": {},
    "mode": "auto",
    "esp_online": False,
    "last_seen": 0.0,
    "broker_ok": False,
}
_loop: asyncio.AbstractEventLoop | None = None
_client: mqtt.Client | None = None

# Nhung gi da ghi vao DB, de chi ghi khi co thay doi
_online_logged = False
_prev_motion = False
_prev_gas_alarm = False
_actuator_cache: dict[str, bool] = {}
_mode_cache: str | None = None
_last_db_write = 0.0


class BridgeError(Exception):
    """Loi nghiep vu co ma HTTP, router doi thanh HTTPException."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _log(message: str) -> None:
    print(f"[mqtt] {message}", flush=True)


# ---------------------------------------------------------------- trang thai
def get_state() -> dict[str, Any]:
    """Trang thai truc tiep. `mode` la che do thuc te: uu tien gia tri ESP32 bao ve."""
    with _lock:
        state = dict(_state)
        state["sensors"] = dict(_state["sensors"])

    age = time.time() - state["last_seen"] if state["last_seen"] else None
    alive = age is not None and age < settings.mqtt_offline_after
    state["esp_online"] = bool(state["esp_online"] and alive)
    state["age"] = round(age, 1) if age is not None else None

    reported = str(state["sensors"].get("mode", "")).lower()
    if state["esp_online"] and reported in ("auto", "manual"):
        state["mode"] = reported
    state.pop("last_seen")
    return state


async def _push_live() -> None:
    await manager.broadcast("live", get_state())


# ---------------------------------------------------------------- thiet bi trong DB
def _ensure_device(db: Session, code: str, kind: str, name: str) -> models.Device:
    device = services.get_device_by_code(db, code)
    if device is None:
        device = models.Device(code=code, name=name, kind=kind, room=ROOM)
        db.add(device)
        db.flush()
    return device


def _sensor_device(db: Session) -> models.Device:
    return _ensure_device(db, SENSOR_CODE, "sensor", SENSOR_NAME)


def _all_devices(db: Session) -> list[models.Device]:
    devices = [_sensor_device(db)]
    devices += [_ensure_device(db, code, kind, name) for code, kind, name in ACTUATORS.values()]
    return devices


def ensure_devices(db: Session) -> None:
    """Tao san 4 thiet bi (1 cam bien + den/quat/loa) neu chua co."""
    _all_devices(db)
    db.commit()


async def _set_online(db: Session, online: bool) -> None:
    global _online_logged
    _online_logged = online
    now = services.utcnow()
    devices = _all_devices(db)
    for device in devices:
        device.online = online
        if online:
            device.last_seen = now
    db.flush()
    for device in devices:
        await manager.broadcast("device", services.device_payload(device))
    await services.log_event(
        db,
        type="device_online" if online else "device_offline",
        severity="info" if online else "warning",
        message="ESP32 da ket noi" if online else "ESP32 mat ket noi",
        device=devices[0],
    )


async def _sync_auto_flags(db: Session, mode: str) -> None:
    """Co auto_mode cua den/quat/loa theo che do he thong (de trang Thiet bi hien dung)."""
    global _mode_cache
    _mode_cache = mode
    for code, kind, name in ACTUATORS.values():
        device = _ensure_device(db, code, kind, name)
        if device.auto_mode != (mode == "auto"):
            device.auto_mode = mode == "auto"
            db.flush()
            await manager.broadcast("device", services.device_payload(device))


def _num(value: Any) -> float | None:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)) and value == value:  # loai NaN
        return float(value)
    return None


async def _store_readings(db: Session, sensor: models.Device, data: dict[str, Any]) -> None:
    stamp = services.utcnow()
    sensor.last_seen = stamp
    values = {metric: _num(data.get(src)) for src, metric in METRIC_KEYS.items()}
    values["motion"] = 1.0 if data.get("motion") else 0.0
    for metric, value in values.items():
        if value is None:
            continue
        db.add(models.Reading(device_id=sensor.id, metric=metric, value=value, ts=stamp))
        await manager.broadcast(
            "reading",
            {
                "device_id": sensor.id,
                "device_code": sensor.code,
                "metric": metric,
                "value": value,
                "ts": stamp,
            },
        )
    cloud_sink.enqueue(
        sensor.code, {metric: value for metric, value in values.items() if value is not None}, stamp
    )


# ---------------------------------------------------------------- xu ly ban tin
async def _on_sensors(payload: str) -> None:
    global _prev_motion, _prev_gas_alarm, _last_db_write
    try:
        data = json.loads(payload)
    except ValueError:
        return
    if not isinstance(data, dict):
        return

    now = time.time()
    with _lock:
        _state["sensors"] = data
        _state["last_seen"] = now
        _state["esp_online"] = True

    motion = bool(data.get("motion"))
    gas_alarm = bool(data.get("gas_alarm"))
    motion_edge = motion and not _prev_motion
    gas_on = gas_alarm and not _prev_gas_alarm
    gas_off = _prev_gas_alarm and not gas_alarm
    _prev_motion, _prev_gas_alarm = motion, gas_alarm

    changed = {
        key: bool(data[key])
        for key in ACTUATORS
        if key in data and _actuator_cache.get(key) != bool(data[key])
    }
    reported_mode = str(data.get("mode", "")).lower()
    mode_changed = reported_mode in ("auto", "manual") and reported_mode != _mode_cache
    came_online = not _online_logged
    due = now - _last_db_write >= settings.mqtt_history_seconds

    if came_online or due or changed or mode_changed or motion_edge or gas_on or gas_off:
        db = SessionLocal()
        try:
            if came_online:
                await _set_online(db, True)
            sensor = _sensor_device(db)
            if mode_changed:
                await _sync_auto_flags(db, reported_mode)

            for key, state in changed.items():
                code, kind, name = ACTUATORS[key]
                device = _ensure_device(db, code, kind, name)
                _actuator_cache[key] = state
                if device.state != state:
                    device.state = state
                    db.flush()
                    await manager.broadcast("device", services.device_payload(device))

            if due:
                _last_db_write = now
                await _store_readings(db, sensor, data)

            if motion_edge:
                await services.log_event(
                    db, type="motion", message="Phat hien chuyen dong", device=sensor
                )
            if gas_on:
                await services.log_event(
                    db,
                    type="gas_alarm",
                    severity="critical",
                    message=f"Phat hien gas/khoi nguy hiem (ADC={data.get('gas')})",
                    device=sensor,
                )
            if gas_off:
                await services.log_event(
                    db, type="gas_clear", message="Het canh bao gas/khoi", device=sensor
                )
            db.commit()
        finally:
            db.close()

    await _push_live()


async def _check_online() -> None:
    """ESP32 im lang qua mqtt_offline_after giay -> danh dau offline."""
    if _online_logged and not get_state()["esp_online"]:
        db = SessionLocal()
        try:
            await _set_online(db, False)
            db.commit()
        finally:
            db.close()
        await _push_live()


async def tick() -> None:
    """Goi dinh ky tu background_worker."""
    if _client is not None:
        await _check_online()


async def _handle(topic: str, payload: str) -> None:
    try:
        if topic == T_SENSORS:
            await _on_sensors(payload)
        elif topic == T_STATUS:
            with _lock:
                _state["esp_online"] = payload == "online"
            await _check_online()
            await _push_live()
        elif topic == T_MODE and payload in ("auto", "manual"):
            with _lock:
                _state["mode"] = payload  # nhan lai mode retained sau khi server khoi dong lai
            await _push_live()
    except Exception as exc:  # khong de mot ban tin loi lam chet bridge
        _log(f"loi xu ly {topic}: {exc!r}")


# ---------------------------------------------------------------- paho (chay o thread rieng)
def _schedule(coro) -> None:
    if _loop is not None and not _loop.is_closed():
        asyncio.run_coroutine_threadsafe(coro, _loop)
    else:
        coro.close()


def _on_connect(client, userdata, flags, reason_code, properties=None) -> None:
    ok = not reason_code.is_failure
    with _lock:
        _state["broker_ok"] = ok
    if ok:
        client.subscribe([(T_SENSORS, 0), (T_STATUS, 1), (T_MODE, 1)])
        tls = "on" if settings.mqtt_tls else "off"
        _log(
            f"da ket noi broker {settings.mqtt_host}:{settings.mqtt_port}, tls={tls}, prefix={PREFIX}"
        )
    else:
        _log(f"ket noi broker that bai: {reason_code}")
    _schedule(_push_live())


def _on_disconnect(client, userdata, flags, reason_code, properties=None) -> None:
    with _lock:
        _state["broker_ok"] = False
    _log("mat ket noi broker, dang thu lai...")
    _schedule(_push_live())


def _on_message(client, userdata, msg) -> None:
    payload = msg.payload.decode(errors="ignore").strip()
    _schedule(_handle(msg.topic, payload))


def start(loop: asyncio.AbstractEventLoop) -> None:
    global _client, _loop
    if not settings.mqtt_enabled:
        _log("MQTT_ENABLED=false -> bo qua cau noi MQTT")
        return
    if _client is not None:
        return
    _loop = loop
    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2, client_id=f"fastapi-{uuid.uuid4().hex[:8]}"
    )
    if settings.mqtt_user:
        client.username_pw_set(settings.mqtt_user, settings.mqtt_pass)
    if settings.mqtt_tls:
        client.tls_set()  # OS CA store; HiveMQ Cloud uses a Let's Encrypt chain
    client.on_connect = _on_connect
    client.on_disconnect = _on_disconnect
    client.on_message = _on_message
    client.reconnect_delay_set(1, 10)
    client.connect_async(settings.mqtt_host, settings.mqtt_port, keepalive=30)
    client.loop_start()
    _client = client


def stop() -> None:
    global _client
    if _client is not None:
        _client.loop_stop()
        _client.disconnect()
        _client = None


# ---------------------------------------------------------------- lenh tu giao dien
def _require_broker() -> dict[str, Any]:
    state = get_state()
    if _client is None or not state["broker_ok"]:
        raise BridgeError(503, "Chua ket noi duoc MQTT broker")
    return state


async def set_mode(db: Session, mode: str) -> None:
    """Doi che do auto/manual: publish retained de ESP32 (va server khi khoi dong lai) nhan duoc."""
    _require_broker()
    with _lock:
        _state["mode"] = mode
    _client.publish(T_MODE, mode, qos=1, retain=True)
    await services.log_event(
        db,
        type="manual",
        message=f"Nguoi dung chuyen sang che do {'tu dong' if mode == 'auto' else 'thu cong'}",
    )
    await _push_live()


async def manual_command(db: Session, key: str, state: bool) -> models.Device:
    """Bat/tat den/quat/loa o che do thu cong (publish cmd/<key> = ON|OFF)."""
    current = _require_broker()
    if current["mode"] != "manual":
        raise BridgeError(409, "Chi dieu khien duoc o che do thu cong")
    if not current["esp_online"]:
        raise BridgeError(503, "ESP32 dang offline")

    _client.publish(T_CMD + key, "ON" if state else "OFF", qos=1, retain=False)

    code, kind, name = ACTUATORS[key]
    device = _ensure_device(db, code, kind, name)
    device.state = state  # lac quan; ban tin sensors tiep theo cua ESP32 se xac nhan
    db.flush()
    await manager.broadcast("device", services.device_payload(device))
    await services.log_event(
        db,
        type="manual",
        message=f"Nguoi dung {'bat' if state else 'tat'} {name}",
        device=device,
    )
    return device
