# Live sensor dashboard redesign

Status: draft · Date: 2026-10-24

## Problem

The ESP32 now publishes this JSON on `<MQTT_PREFIX>sensors` (see `publishSensors()` in `smart-home/firmware/esp32_smart_home/esp32_smart_home.ino`):

```json
{"ldr":218,"dark":false,"temp":31.3,"hum":69.4,"gas":137,"gas_base":157,"gas_alarm":false,
 "motion":true,"light":false,"fan":false,"buzzer":false,"mode":"auto"}
```

The Overview page shows it as five flat `StatCard`s (`frontend/src/components/LiveSensors.tsx`). Problems with that:

- `gas_base` (the MQ-2 baseline measured at boot) is ignored, so the raw ADC number means nothing to a user. The firmware alarms when the smoothed reading passes `gas_base + 500` and clears below `gas_base + 250`.
- The "Độ sáng (LDR)" card shows raw ADC where a higher value means darker (`dark = ldr > 2000`), which reads backwards.
- There is no trend. A single number doesn't show whether a value is rising, steady or noisy.
- When the ESP32 goes offline, every value turns into `--`, which hides the last known state.
- In auto mode the user can't tell why the fan or light is on.

Patterns from current smart-home dashboards that this spec borrows:
- Apple Home (iOS 16+): a row of category summaries at the top of the Home screen (Climate shows the temperature range, Lights shows how many are on, Security shows lock state), so the whole home reads at a glance ([TechHive](https://www.techhive.com/article/782146/apple-tees-up-a-redesigned-home-app-for-ios-16.html), [MacStories](https://www.macstories.net/stories/everything-new-coming-to-the-home-app-in-ios-16-and-macos-ventura/), [Jorge Arango on the IA](https://jarango.com/2022/06/07/apple-home-app-redesign/)). Accessory tiles light up when the device is on.
- Home Assistant Sections view and tile cards: one clear primary action per tile, small sparklines and mini progress bars for monitoring, 8 px gutters, 36 px icons ([HA dashboard chapter 2](https://www.home-assistant.io/blog/2024/07/26/dashboard-chapter-2/)). Mushroom template cards change icon colour and badge by state, red/orange only when something needs attention ([SmartHomeScene](https://smarthomescene.com/guides/mushroom-cards-complete-guide-to-a-clean-minimalistic-home-assistant-ui/), [housecontrollers.de](https://www.housecontrollers.de/smart-home/home-assistant-dashboards/)).
- Tile plus banded gauge for "higher is worse" readings such as air quality ([Apollo wiki](https://wiki.apolloautomation.com/products/ESPHome-Starter-Kit/everyday-use/air-quality-on-your-dashboard/)).
- Value plus sparkline, so the trend sits behind the number ([ThingsBoard](https://thingsboard.io/iot-hub/widgets/simple-value-and-chart-card/), [PatternFly trend cards](https://v5-archive.patternfly.org/patterns/dashboard/design-guidelines)).
- Blynk-style gauge for the current value and a chart for history ([Blynk blueprint](https://blynk.io/blueprints/weather-monitoring-with-esp32-with-static-tokens)).
- Device cards show name, status and one primary action; offline must look different from "off"; every action gets visible feedback ([Design Monks](https://www.designmonks.co/blog/home-automation-app-ui-design)). Dark smart-home concepts favour a single-glance overview and warn about low-contrast secondary text ([Contra case study](https://contra.com/p/RFXAsELR-smart-home-mobile-app-full-case-study), [UXCel critique](https://app.uxcel.com/showcase/smart-home-dashboard-ux-design-324)).

## Goals

- Replace the live sensor row on the Overview page with: a row of four Apple-Home-style summary tiles (An toàn, Khí hậu, Ánh sáng, Thiết bị), and five sensor tiles that each show a value, a derived label and a 5-minute sparkline.
- Gas tile: a semicircle gauge of `gas − gas_base` with bands at +250 and +500.
- Light tile: brightness in percent with a bar marking the dark threshold.
- Temperature tile: heat index ("cảm nhận") and a comfort label from temperature and humidity.
- Motion tile: present/absent, plus "lần cuối X phút trước" when nobody is present.
- Actuator panel: each device becomes a tile that lights up in its own colour when on, with a one-line reason for why it is on.
- Offline: keep the last values, dimmed, with a "Mất tín hiệu · Ns trước" chip.
- One visual language across the new pieces: per-sensor colours from `CHART_COLORS`, status colours only for state.

## Non-goals

- No firmware change and no MQTT contract change. Thresholds are mirrored as frontend constants.
- No backend schema change. `gas_base` is not stored in `readings`.
- No change to `SensorChart`, `ActivityChart`, `EventFeed`, `VideoSlot`, the Devices, Automations or Events pages.
- No new npm dependency. No light theme. No new Tailwind theme colours; the only palette change is three keys added to `CHART_COLORS` (see `ActuatorPanel.tsx`).
- No change to the actuator control logic (pending state, `sendCommand`, the 409/503 messages). Only the markup and styling of `ActuatorPanel` change.
- No room grouping or floor plan: there is one ESP32 in one room.
- Sparkline history does not survive a page reload (in-memory only).

## Design

### Visual language

Builds on the existing dark theme (`ink-950` page, `ink-900` `.card`, `brand` teal, `rounded-2xl`, `shadow-card` in `tailwind.config.ts` and `globals.css`).

- **Sensor colour** (identity): `CHART_COLORS` from `lib/chartTheme.ts`, already checked for ≥ 3:1 contrast on `#0B1222`. Temperature `#d95926`, humidity `#3987e5`, light `#c98500`, gas `#e66767`, motion `#3987e5`. Used for the tile icon (`style={{ color }}` on the icon, background `color + "26"` ≈ 15 % alpha), the sparkline stroke and the history chart, so the same metric has the same colour everywhere on the page.
- **Status colour** (state): emerald (`brand`) = normal/safe, amber = needs attention (elevated gas, dark + nobody, hot), rose = danger (gas alarm, offline). Status colours only appear on badges, the gauge bands, the summary tile accent and the offline chip, never as sensor identity. Rose and amber always come with a text label, not colour alone.
- **Typography**: label `muted` (12 px, `slate-500`), value `text-3xl font-semibold tabular-nums text-white`, unit `text-base text-slate-400` next to the value, secondary text at least `slate-400` (not `slate-500`) when it carries data, per the low-contrast warning above.
- **Spacing and shape**: grid `gap-4` (existing), tiles `rounded-2xl p-5`, icons 36 px boxes (`h-9 w-9 rounded-xl`) with 18 px glyphs, sparkline 32 px tall bleeding to the tile's bottom edge (`-mx-5 -mb-5`, rounded bottom corners).
- **Motion**: transitions `transition-colors duration-300` on state change; fan icon spins when on (existing); gas danger icon pulses (existing `animate-pulse`). Respect `motion-reduce:animate-none` on both.
- **Stale**: `opacity-60`, sparkline stroke `slate-600`, gauge track `slate-700`. Distinct from "off", which keeps full opacity.

### Summary row: `frontend/src/components/HomeSummary.tsx` (new)

Four tiles in `grid grid-cols-2 gap-4 lg:grid-cols-4`, each `card` with a 36 px icon, a title and two lines:

| Tile | Icon | Line 1 | Line 2 | Accent |
|---|---|---|---|---|
| An toàn | `ShieldCheck` / `ShieldAlert` | "Không có gas" / "PHÁT HIỆN GAS" | "Có người" / "Không có người" | brand / rose (pulsing icon) |
| Khí hậu | `Thermometer` | `31.3° · 69%` | comfort label | brand; amber for Nóng/Nóng ẩm/Lạnh |
| Ánh sáng | `Sun` / `Moon` | `Sáng · 95%` / `Tối · 12%` | "Đèn bật" / "Đèn tắt" | brand / amber when dark and light off while someone is present |
| Thiết bị | `Power` | `1/3 đang bật` | "Tự động" / "Thủ công" | brand |

Accent = left border `border-l-2` plus icon tint. When offline, a full-width chip "Mất tín hiệu · {age}s trước" (or "Chưa nhận được dữ liệu" when `age` is null) sits above the row, and the four tiles get stale styling. Tiles are not clickable (no detail pages in scope).

### Pure logic: `smart-home/frontend/src/lib/sensorLogic.ts` (new)

No imports, so it can run under `node --test` with Node 24 type stripping. Contains:

```ts
// Must match esp32_smart_home.ino. Changing them there without changing them here makes the UI wrong.
export const LDR_MAX = 4095;
export const LDR_DARK_THRESHOLD = 2000;
export const TEMP_ON = 31.5;
export const TEMP_OFF = 28.0;
export const GAS_ON_OFFSET = 500;
export const GAS_OFF_OFFSET = 250;
export const GAS_GAUGE_MAX = 750; // 1.5 × GAS_ON_OFFSET
export const LIVE_WINDOW_MS = 5 * 60_000;
export const LIVE_MAX_SAMPLES = 300;

export function brightnessPercent(ldr: number): number
//   clamp(round((LDR_MAX - ldr) / LDR_MAX * 100), 0, 100). 218 -> 95, 2000 -> 51, 4095 -> 0.

export type GasLevel = "normal" | "elevated" | "danger";
export function gasStatus(gas: number, base: number | undefined, alarm: boolean):
  { delta: number | null; level: GasLevel; ratio: number }
//   delta = base === undefined ? null : gas - base
//   level = alarm ? "danger" : delta !== null && delta >= GAS_OFF_OFFSET ? "elevated" : "normal"
//   ratio = delta === null ? 0 : clamp(delta / GAS_GAUGE_MAX, 0, 1)
//   gas_alarm from the ESP32 wins: the firmware alarms on the smoothed value, the payload carries raw.

export function heatIndexC(tempC: number, hum: number): number
//   NOAA: simple formula; if its result >= 80°F use Rothfusz regression with the
//   standard low/high humidity adjustments. Input and output in °C, rounded to 0.1.

export type Comfort = "Lạnh" | "Nóng ẩm" | "Nóng" | "Khô" | "Ẩm" | "Thoải mái";
export function comfortLabel(tempC: number, hum: number): Comfort
//   first match wins: temp < 18 "Lạnh"; temp > 30 && hum >= 60 "Nóng ẩm"; temp > 30 "Nóng";
//   hum < 30 "Khô"; hum > 70 "Ẩm"; else "Thoải mái".

export function actuatorReason(key: "light" | "fan" | "buzzer", s: SensorsLike): string | null
//   null when the device is off. mode "manual" -> "Điều khiển thủ công".
//   Auto: light -> "Trời tối + có người"; buzzer -> "Báo động gas";
//   fan -> gas_alarm ? "Xả gas" : `Làm mát (≥ ${TEMP_ON}°C)`.

export interface LiveSample { t: number; temp?: number; hum?: number; ldr?: number; gas?: number;
                              gasDelta?: number; motion?: boolean }
export function appendSample(buf: LiveSample[], sample: LiveSample): LiveSample[]
//   Returns a new array. Drops the sample if sample.t - last.t < 500 ms (duplicate live push, or older than the last sample).
//   Drops samples older than sample.t - LIVE_WINDOW_MS, then keeps the last LIVE_MAX_SAMPLES.

export function lastMotionAt(buf: LiveSample[]): number | null
//   t of the newest sample with motion === true, or null.
```

`SensorsLike` is a local structural type (`{ mode?, gas_alarm?, light?, fan?, buzzer? }`) so the file stays import-free.

### Types: `frontend/src/lib/types.ts`

Add `gas_base?: number` to `LiveSensors`. Re-export nothing; `LiveSample` lives in `sensorLogic.ts`.

### Live buffer: `frontend/src/components/DashboardProvider.tsx`

- New state `liveHistory: LiveSample[]`, exposed on the context.
- On every `live` message and on the initial `api.live()` result: if `esp_online` and `sensors` is non-empty, build a sample with `t = Date.now() - (age ?? 0) * 1000` and `setLiveHistory(h => appendSample(h, sample))`.
- Not seeded from `/series`.

### New components (`frontend/src/components/`)

- `Sparkline.tsx`: inline SVG polyline, `viewBox` 0 0 100 32, `preserveAspectRatio="none"`, stroke `currentColor`. Props `values: number[]`, optional `min`/`max`. Renders nothing for fewer than 2 points. No Recharts (five `ResponsiveContainer`s for 32-px charts is overkill).
- `GasGauge.tsx`: SVG semicircle. Track split into three arcs coloured by band (0–250 emerald, 250–500 amber, 500–750 rose), needle or filled arc at `ratio`. Grey track when stale.
- `SensorTile.tsx`: card with icon, label, big value, `hint` line, optional `badge` (comfort/level chip), optional `children` slot (gauge, bar, sparkline). `stale` prop adds `opacity-60` and greys tone colours. Same `TONES` as `StatCard`.

### Rewritten: `frontend/src/components/LiveSensors.tsx`

Renders `<HomeSummary />` above a `grid gap-4 sm:grid-cols-2 xl:grid-cols-5` of five `SensorTile`s:

| Tile | Value | Hint | Badge | Body |
|---|---|---|---|---|
| Nhiệt độ | `31.3°C` | `Cảm nhận 38.2°C · quạt bật ≥ 31.5°C` | comfort label | sparkline of `temp` |
| Độ ẩm | `69%` | `DHT22` | comfort label | sparkline of `hum` |
| Ánh sáng | `95%` | `ADC 218 · ngưỡng tối 51%` | "Sáng"/"Tối" from `dark` | horizontal bar with a marker at `brightnessPercent(LDR_DARK_THRESHOLD)`, sparkline of brightness |
| Gas/khói | `+0` (delta, clamped display ≥ 0 shown as signed) | `ADC 137 · nền 157` | "Bình thường"/"Tăng cao"/"Nguy hiểm" | `GasGauge`, sparkline of delta |
| Chuyển động | "Có người"/"Không có người" | "Lần cuối 2 phút trước" or "Cảm biến PIR" | — | 5-minute presence strip (filled segments where `motion` was true) |

"Lần cuối": `lastMotionAt(liveHistory)`; if null, the newest `motion` event in `events` from the provider; if neither, "Cảm biến PIR". Uses `timeAgo` from `lib/format.ts`.

Missing `gas_base` (old firmware, current simulator before this change): value shows raw ADC, hint "Chưa có giá trị nền", no gauge bands (grey track), sparkline of raw `gas`.

### Changed: `ActuatorPanel.tsx`

The divided list becomes three tiles (`grid gap-3`, one column inside the existing `xl:col-span-1` slot, three columns below `xl` via `sm:grid-cols-3 xl:grid-cols-1`). Each tile, Apple-Home style:

- Off: `bg-white/[0.03] border-white/5`, icon `slate-400`, status "Đang tắt".
- On: tinted with the device colour, background at ~12 % and border at ~30 %: light amber (`#c98500`), fan blue (`#3987e5`, icon spins), buzzer rose (`#e66767`, icon pulses). Status "Đang bật" in that colour.
- Below the status, the `actuatorReason` line (`text-xs text-slate-400`), or "—" when off.
- The existing Bật/Tắt segmented control stays on the right of the tile, same `disabled` rules, same pending text "· đang gửi lệnh...".
- Offline ESP32: tiles get stale styling, so offline never looks like "off".

Add these three colours to `CHART_COLORS` as `light`, `fan`, `buzzer` (reusing the existing hex values) rather than hard-coding them in the component.

### Changed: `GasAlertBanner.tsx`

Text becomes `Nồng độ (ADC): {gas} · vượt nền +{gas - gas_base}` when `gas_base` is present; otherwise unchanged.

### Changed: `smart-home/backend/simulator_mqtt.py`

Add `"gas_base": 800` to the payload and compute `gas_alarm = gas > 800 + 500`, so the simulator matches the firmware payload. Update the topic docstring in `app/mqtt_bridge.py` to list `gas_base`.

### Layout of the Overview page

`frontend/src/app/page.tsx` keeps its order. `<LiveSensors />` now includes the summary row, so nothing else in the page moves. Order from top: mode switch + connection, summary row, sensor tiles, actuator tiles + video, history chart + events, activity, stat cards.

## Data and API changes

- REST/WebSocket: none. `LiveOut.sensors` is `dict[str, Any]` (`backend/app/schemas.py:178`), so `gas_base` already reaches `/api/live` and the `live` WebSocket message.
- DB: none.
- MQTT: none (firmware already sends `gas_base`).
- Simulator payload gains `gas_base` (dev tool only).

## Edge cases and errors

- `sensors` empty (backend just started, no message yet): tiles show `--`, no sparkline, offline chip reads "Chưa nhận được dữ liệu".
- ESP32 offline (`esp_online=false`): tiles keep last values with `stale` styling; no samples are appended, so sparklines freeze.
- A field is missing or not a number (`_num` in the backend does not filter the live dict): the tile shows `--` for that field; `appendSample` stores `undefined` and `Sparkline` skips non-finite values.
- `gas < gas_base` (normal after warm-up; example payload has 137 vs 157): delta is negative, gauge ratio clamps to 0, value shows the signed delta (`−20`).
- `gas_alarm=true` while `delta < 500` (smoothed vs raw mismatch): level is "danger"; gauge shows the actual delta but the gas badge and the An toàn summary tile are rose.
- `ldr` outside 0–4095: brightness clamps to 0–100.
- Thresholds changed over Serial (`GASON=...`, `TEMPON=...`): UI bands and the fan hint will be off until `sensorLogic.ts` is edited. Documented in the constants comment.
- Duplicate `live` pushes (status topic, mode topic, reconnect): deduped by the 500 ms rule.
- Tab left open for hours: buffer is capped at 300 samples / 5 minutes.
- Fan on in auto with `temp < TEMP_ON` (hysteresis between 28 and 31.5): reason still says "Làm mát (≥ 31.5°C)"; acceptable, it names the rule, not the current reading.

## Test plan

Unit tests in `smart-home/frontend/tests/sensorLogic.test.mjs`, using `node:test` and `node:assert`, importing `../src/lib/sensorLogic.ts` (Node 24 strips types; the `.mjs` file is outside the `tsconfig` include patterns so `tsc` ignores it). Run: `node --test "tests/*.test.mjs"` from `smart-home/frontend/`.

- `brightnessPercent`: 218 → 95, 2000 → 51, 0 → 100, 4095 → 0, -5 → 100, 5000 → 0.
- `gasStatus`: (137, 157, false) → delta −20, normal, ratio 0; (500, 157, false) → elevated; (700, 157, false) → elevated (alarm flag false wins over raw); (300, 157, true) → danger; (900, undefined, false) → delta null, ratio 0; (1200, 157, false) → ratio 1.
- `heatIndexC`: (31.3, 69.4) within ±0.3 of 38.2; (25, 50) within ±0.5 of 25 (simple-formula branch).
- `comfortLabel`: (15, 50) Lạnh, (31.3, 69.4) Nóng ẩm, (32, 40) Nóng, (24, 25) Khô, (24, 80) Ẩm, (24, 55) Thoải mái.
- `actuatorReason`: off → null; manual + on → "Điều khiển thủ công"; auto fan with gas_alarm → "Xả gas"; auto fan without → contains "Làm mát"; auto light → "Trời tối + có người".
- `appendSample`: drops a sample 200 ms after the last; drops samples older than 5 min; never exceeds 300; returns a new array.
- `lastMotionAt`: null on empty; returns newest motion=true t.

Build checks from `smart-home/frontend/`: `npx tsc --noEmit` and `npm run build` pass. From `smart-home/backend/`: `.venv/Scripts/python -m compileall -q app simulator.py simulator_mqtt.py` passes.

End-to-end check: backend with MQTT enabled, `npm run dev`, then `.venv/Scripts/python simulator_mqtt.py --prefix ptit_sh_k7x2q9/home/ --gas-at 30`. Within 30 s the Overview shows sparklines growing in all tiles and `gas_base` 800 in the gas hint; at ~30 s the gas gauge goes rose, the An toàn tile reads "PHÁT HIỆN GAS", the fan tile lights blue with reason "Xả gas" and the buzzer tile lights rose; after Ctrl+C on the simulator, within `MQTT_OFFLINE_AFTER` seconds the tiles dim and the chip reads "Mất tín hiệu".

## Acceptance criteria

- [ ] `node --test "tests/*.test.mjs"` in `smart-home/frontend/` passes, covering every function in `sensorLogic.ts`.
- [ ] `npx tsc --noEmit` and `npm run build` pass in `smart-home/frontend/`.
- [ ] `compileall` passes for the backend including `simulator_mqtt.py`.
- [ ] `git diff --stat` shows no change to `package.json`, `package-lock.json`, `backend/app/models.py`, `backend/app/schemas.py` or the `.ino`.
- [ ] With the simulator running, `/api/live` returns `sensors.gas_base == 800`.
- [ ] With the simulator running, the Overview shows the four summary tiles and five sensor tiles; the light tile shows a percentage, not raw ADC as the main value.
- [ ] With `--gas-at`, the gas gauge band, gas badge, An toàn summary tile, fan tile and buzzer tile all switch to the danger/"Xả gas" state while `gas_alarm` is true, and return when it clears.
- [ ] After stopping the simulator, tiles keep their last values with dimmed styling and the "Mất tín hiệu" chip, instead of `--`.
- [ ] At 375 px width the Overview has no horizontal scroll; the summary row is 2 columns and actuator tiles stack.
- [ ] In manual mode with the simulator, pressing "Bật" on Đèn lights the tile amber after the next `sensors` message, and the reason line reads "Điều khiển thủ công".
- [ ] With the ESP32 offline, actuator tiles are dimmed and their Bật/Tắt controls are disabled, visually distinct from an online device that is off.

## Open questions

- Comfort bands (18 °C, 30 °C, 30 %, 60 %, 70 %) are a reasonable default for a hot, humid climate; adjust if the course has a reference.
- If the thresholds start being tuned over Serial during demos, the next step is a retained `<prefix>config` topic from the firmware. That is a contract change and a reflash, so it is out of scope here.
