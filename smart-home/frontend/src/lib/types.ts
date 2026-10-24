export type DeviceKind = "sensor" | "fan" | "light" | "alarm";

export interface Device {
  id: number;
  code: string;
  name: string;
  kind: DeviceKind;
  room: string;
  online: boolean;
  state: boolean;
  auto_mode: boolean;
  last_seen: string | null;
  created_at: string;
}

export type Severity = "info" | "warning" | "critical";

export interface SmartEvent {
  id: number;
  device_id: number | null;
  device_name: string | null;
  type: string;
  severity: Severity;
  message: string;
  acknowledged: boolean;
  ts: string;
}

export interface Automation {
  id: number;
  name: string;
  enabled: boolean;
  metric: string;
  operator: "gt" | "gte" | "lt" | "lte" | "eq";
  threshold: number;
  source_device_id: number | null;
  target_device_id: number;
  action: "on" | "off";
  auto_off_seconds: number;
  cooldown_seconds: number;
  last_triggered: string | null;
  target_device_name: string | null;
  source_device_name: string | null;
}

export interface Summary {
  devices_total: number;
  devices_online: number;
  actuators_on: number;
  temperature: number | null;
  humidity: number | null;
  lux: number | null;
  motion_last_24h: number;
  falls_last_24h: number;
  unacknowledged_alerts: number;
  last_fall: SmartEvent | null;
}

export interface MetricSeries {
  metric: string;
  points: { ts: string; value: number }[];
}

export interface ActivityBucket {
  hour: string;
  motion: number;
  fall: number;
  automation: number;
}

export type SystemMode = "auto" | "manual";
export type ControlKey = "light" | "fan" | "buzzer";

/** JSON cảm biến ESP32 gửi qua MQTT (cùng định dạng với bản Django). */
export interface LiveSensors {
  ldr?: number;
  dark?: boolean;
  temp?: number;
  hum?: number;
  gas?: number;
  /** MQ-2 baseline measured at boot; the firmware alarms at gas_base + 500. */
  gas_base?: number;
  gas_alarm?: boolean;
  motion?: boolean;
  mode?: SystemMode;
  light?: boolean;
  fan?: boolean;
  buzzer?: boolean;
}

/** Trạng thái trực tiếp từ ESP32: cảm biến mới nhất + chế độ + trạng thái kết nối. */
export interface LiveState {
  sensors: LiveSensors;
  mode: SystemMode;
  esp_online: boolean;
  broker_ok: boolean;
  age: number | null;
}

/** Mã thiết bị do ESP32 quản lý qua MQTT (khớp backend/app/bridge_devices.py). */
export const MQTT_DEVICE_CODES: Record<string, ControlKey | "sensor"> = {
  "esp32-main": "sensor",
  "light-main": "light",
  "fan-main": "fan",
  "buzzer-main": "buzzer",
};

/** Tin nhắn realtime backend đẩy qua WebSocket. */
export type RealtimeMessage =
  | { type: "live"; data: LiveState }
  | { type: "device"; data: Device }
  | { type: "event"; data: SmartEvent }
  | { type: "reading"; data: { device_id: number; device_code: string; metric: string; value: number; ts: string } }
  | { type: "automation"; data: { id: number; last_triggered: string } };
