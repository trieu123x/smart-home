// Pure sensor logic for the live dashboard. No imports, so `node --test` can load it with type stripping.

// Must match esp32_smart_home.ino. Changing them there (or over Serial: GASON=, TEMPON=, ...)
// without changing them here makes the UI wrong.
export const LDR_MAX = 4095;
export const LDR_DARK_THRESHOLD = 2000;
export const TEMP_ON = 31.5;
export const TEMP_OFF = 28.0;
export const GAS_ON_OFFSET = 500;
export const GAS_OFF_OFFSET = 250;
export const GAS_GAUGE_MAX = 750; // 1.5 × GAS_ON_OFFSET
export const LIVE_WINDOW_MS = 5 * 60_000;
export const LIVE_MAX_SAMPLES = 300;

/** Minimum gap between two samples; closer pushes (status, mode, reconnect) repeat the same reading. */
const DUPLICATE_MS = 500;

const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value));

/** LDR ADC (higher = darker) to brightness in percent (higher = brighter). */
export function brightnessPercent(ldr: number): number {
  return clamp(Math.round(((LDR_MAX - ldr) / LDR_MAX) * 100), 0, 100);
}

export type GasLevel = "normal" | "elevated" | "danger";

/**
 * Gas reading relative to the boot-time baseline. `alarm` from the ESP32 wins:
 * the firmware alarms on the smoothed value while the payload carries the raw one.
 */
export function gasStatus(
  gas: number,
  base: number | undefined,
  alarm: boolean,
): { delta: number | null; level: GasLevel; ratio: number } {
  const delta = base === undefined ? null : gas - base;
  const level: GasLevel = alarm
    ? "danger"
    : delta !== null && delta >= GAS_OFF_OFFSET
      ? "elevated"
      : "normal";
  const ratio = delta === null ? 0 : clamp(delta / GAS_GAUGE_MAX, 0, 1);
  return { delta, level, ratio };
}

/** NOAA heat index ("feels like"), °C in and out, rounded to 0.1. */
export function heatIndexC(tempC: number, hum: number): number {
  const t = (tempC * 9) / 5 + 32;
  let hi = 0.5 * (t + 61 + (t - 68) * 1.2 + hum * 0.094);
  if (hi >= 80) {
    hi =
      -42.379 +
      2.04901523 * t +
      10.14333127 * hum -
      0.22475541 * t * hum -
      0.00683783 * t * t -
      0.05481717 * hum * hum +
      0.00122874 * t * t * hum +
      0.00085282 * t * hum * hum -
      0.00000199 * t * t * hum * hum;
    if (hum < 13 && t >= 80 && t <= 112) {
      hi -= ((13 - hum) / 4) * Math.sqrt((17 - Math.abs(t - 95)) / 17);
    } else if (hum > 85 && t >= 80 && t <= 87) {
      hi += ((hum - 85) / 10) * ((87 - t) / 5);
    }
  }
  return Math.round((((hi - 32) * 5) / 9) * 10) / 10;
}

export type Comfort = "Lạnh" | "Nóng ẩm" | "Nóng" | "Khô" | "Ẩm" | "Thoải mái";

/** Comfort bands tuned for a hot, humid climate. First match wins. */
export function comfortLabel(tempC: number, hum: number): Comfort {
  if (tempC < 18) return "Lạnh";
  if (tempC > 30 && hum >= 60) return "Nóng ẩm";
  if (tempC > 30) return "Nóng";
  if (hum < 30) return "Khô";
  if (hum > 70) return "Ẩm";
  return "Thoải mái";
}

export interface SensorsLike {
  mode?: string;
  gas_alarm?: boolean;
  light?: boolean;
  fan?: boolean;
  buzzer?: boolean;
}

/** One-line reason why an actuator is on, or null when it is off. Names the firmware rule. */
export function actuatorReason(key: "light" | "fan" | "buzzer", s: SensorsLike): string | null {
  if (!s[key]) return null;
  if (s.mode === "manual") return "Điều khiển thủ công";
  if (key === "light") return "Trời tối + có người";
  if (key === "buzzer") return "Báo động gas";
  return s.gas_alarm ? "Xả gas" : `Làm mát (≥ ${TEMP_ON}°C)`;
}

export interface LiveSample {
  t: number;
  temp?: number;
  hum?: number;
  ldr?: number;
  gas?: number;
  gasDelta?: number;
  motion?: boolean;
}

/**
 * Returns a new buffer with `sample` added and trimmed to the live window. A duplicate push, or a
 * sample older than the last one (a slow `/api/live` landing after a newer WebSocket push),
 * returns `buf` itself, so a React state setter skips the re-render.
 */
export function appendSample(buf: LiveSample[], sample: LiveSample): LiveSample[] {
  const last = buf[buf.length - 1];
  if (last && sample.t - last.t < DUPLICATE_MS) return buf;
  const since = sample.t - LIVE_WINDOW_MS;
  return [...buf.filter((item) => item.t >= since), sample].slice(-LIVE_MAX_SAMPLES);
}

/** Time (ms) of the newest sample with motion, or null. */
export function lastMotionAt(buf: LiveSample[]): number | null {
  for (let i = buf.length - 1; i >= 0; i--) {
    if (buf[i].motion === true) return buf[i].t;
  }
  return null;
}
