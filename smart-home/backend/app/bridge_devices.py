"""Cac thiet bi trong DB tuong ung voi ESP32 noi qua MQTT.

Dung chung cho mqtt_bridge, services va routers (tach rieng de tranh import vong).
"""

SENSOR_CODE = "esp32-main"
SENSOR_NAME = "Cam bien ESP32"
ROOM = "Phong chinh"

# khoa trong JSON/topic MQTT -> (ma thiet bi trong DB, loai, ten hien thi)
ACTUATORS: dict[str, tuple[str, str, str]] = {
    "light": ("light-main", "light", "Den"),
    "fan": ("fan-main", "fan", "Quat"),
    "buzzer": ("buzzer-main", "alarm", "Loa bao dong"),
}

BRIDGED_CODES: frozenset[str] = frozenset(
    {SENSOR_CODE, *(code for code, _, _ in ACTUATORS.values())}
)
KEY_BY_CODE: dict[str, str] = {code: key for key, (code, _, _) in ACTUATORS.items()}
