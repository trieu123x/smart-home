"use client";

import clsx from "clsx";
import { Droplets, Flame, PersonStanding, Sun, Thermometer } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { CHART_COLORS } from "@/lib/chartTheme";
import { timeAgo } from "@/lib/format";
import {
  LDR_DARK_THRESHOLD,
  LIVE_WINDOW_MS,
  TEMP_ON,
  brightnessPercent,
  comfortLabel,
  gasStatus,
  heatIndexC,
  lastMotionAt,
  type Comfort,
  type GasLevel,
  type LiveSample,
} from "@/lib/sensorLogic";

import { useDashboard } from "./DashboardProvider";
import { GasGauge } from "./GasGauge";
import { HomeSummary } from "./HomeSummary";
import { SensorTile } from "./SensorTile";
import type { Tone } from "./StatCard";

const PRESENCE_SEGMENTS = 30;
const DARK_PERCENT = brightnessPercent(LDR_DARK_THRESHOLD);

const COMFORT_TONE: Record<Comfort, Tone> = {
  "Thoải mái": "good",
  Khô: "default",
  Ẩm: "default",
  Nóng: "warning",
  "Nóng ẩm": "warning",
  Lạnh: "warning",
};

const GAS_BADGE: Record<GasLevel, { text: string; tone: Tone }> = {
  normal: { text: "Bình thường", tone: "good" },
  elevated: { text: "Tăng cao", tone: "warning" },
  danger: { text: "Nguy hiểm", tone: "critical" },
};

const num = (value: unknown) =>
  typeof value === "number" && Number.isFinite(value) ? value : undefined;

/** Signed number with a real minus sign: "+0", "−20". */
const signed = (value: number) => (value < 0 ? `−${Math.abs(value)}` : `+${value}`);

/** Re-renders every second so ages and the presence strip stay current. */
function useNow(intervalMs = 1000) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(timer);
  }, [intervalMs]);
  return now;
}

/** Summary row and live sensor tiles, updated on every MQTT message from the ESP32. */
export function LiveSensors() {
  const { live, liveHistory, events } = useDashboard();
  const now = useNow();
  const s = live?.sensors ?? {};
  const stale = !live?.esp_online;

  // Moment of the last ESP32 message, so the offline age keeps counting between pushes
  const seenAt = useMemo(
    () => (live?.age === null || live?.age === undefined ? null : Date.now() - live.age * 1000),
    [live],
  );
  const age = seenAt === null ? null : (now - seenAt) / 1000;

  const temp = num(s.temp);
  const hum = num(s.hum);
  const ldr = num(s.ldr);
  const gas = num(s.gas);
  const gasBase = num(s.gas_base);

  const comfort = temp !== undefined && hum !== undefined ? comfortLabel(temp, hum) : undefined;
  const comfortBadge = comfort && { text: comfort, tone: COMFORT_TONE[comfort] };
  const dark = s.dark ?? (ldr !== undefined ? ldr > LDR_DARK_THRESHOLD : undefined);
  const brightness = ldr === undefined ? undefined : brightnessPercent(ldr);
  const gasInfo = gas === undefined ? undefined : gasStatus(gas, gasBase, !!s.gas_alarm);

  const lastMotion = useMemo(() => {
    const fromLive = lastMotionAt(liveHistory);
    if (fromLive !== null) return new Date(fromLive).toISOString();
    return events.find((event) => event.type === "motion")?.ts ?? null;
  }, [liveHistory, events]);

  // Freeze the strip at the last sample while offline, like the sparklines
  const stripEnd = stale ? (liveHistory[liveHistory.length - 1]?.t ?? now) : now;

  return (
    <div className="space-y-4">
      <HomeSummary sensors={s} stale={stale} age={age} />

      <details className="rounded-2xl border border-white/10 bg-ink-900/40 p-4">
        <summary className="cursor-pointer text-sm font-medium text-slate-300">Chi tiết cảm biến <span className="ml-2 text-xs font-normal text-slate-400">Nhiệt độ, độ ẩm, ánh sáng, gas và chuyển động</span></summary>
      <div className="mt-4 grid gap-4 sm:grid-cols-2 2xl:grid-cols-5">
        <SensorTile
          label="Nhiệt độ"
          icon={Thermometer}
          color={CHART_COLORS.temperature}
          value={temp === undefined ? "--" : temp.toFixed(1)}
          unit="°C"
          hint={
            temp !== undefined && hum !== undefined
              ? `Cảm nhận ${heatIndexC(temp, hum).toFixed(1)}°C · quạt bật ≥ ${TEMP_ON}°C`
              : `Quạt bật ≥ ${TEMP_ON}°C`
          }
          badge={comfortBadge}
          stale={stale}
          trend={liveHistory.map((sample) => sample.temp)}
        />
        <SensorTile
          label="Độ ẩm"
          icon={Droplets}
          color={CHART_COLORS.humidity}
          value={hum === undefined ? "--" : String(Math.round(hum))}
          unit="%"
          hint="Độ ẩm trong không khí"
          badge={comfortBadge}
          stale={stale}
          trend={liveHistory.map((sample) => sample.hum)}
        />
        <SensorTile
          label="Ánh sáng"
          icon={Sun}
          color={CHART_COLORS.ldr}
          value={brightness === undefined ? "--" : String(brightness)}
          unit="%"
          hint={
            ldr === undefined
              ? `Ngưỡng tối ${DARK_PERCENT}%`
              : `Mức sáng ${brightness}% · ngưỡng tối ${DARK_PERCENT}%`
          }
          badge={
            dark === undefined
              ? undefined
              : dark
                ? { text: "Tối", tone: "default" }
                : { text: "Sáng", tone: "good" }
          }
          stale={stale}
          trend={liveHistory.map((sample) =>
            sample.ldr === undefined ? undefined : brightnessPercent(sample.ldr),
          )}
          trendMin={0}
          trendMax={100}
        >
          <BrightnessBar value={brightness} color={CHART_COLORS.ldr} stale={stale} />
        </SensorTile>
        <SensorTile
          label="Gas/khói"
          icon={Flame}
          iconClassName={
            gasInfo?.level === "danger" && !stale
              ? "animate-pulse motion-reduce:animate-none"
              : undefined
          }
          color={CHART_COLORS.gas}
          value={
            gas === undefined
              ? "--"
              : gasInfo?.delta === null || gasInfo?.delta === undefined
                ? String(Math.round(gas))
                : signed(Math.round(gasInfo.delta))
          }
          hint={
            gasBase === undefined
              ? "Đang xác định mức bình thường"
              : `Chênh lệch so với mức bình thường: ${gasInfo?.delta == null ? "--" : signed(Math.round(gasInfo.delta))}`
          }
          badge={gasInfo && GAS_BADGE[gasInfo.level]}
          stale={stale}
          trend={liveHistory.map((sample) =>
            gasBase === undefined ? sample.gas : sample.gasDelta,
          )}
        >
          <GasGauge
            ratio={gasInfo?.ratio ?? 0}
            banded={gasBase !== undefined && gas !== undefined}
            stale={stale}
            className="mx-auto block h-16 w-full max-w-[8.5rem]"
          />
        </SensorTile>
        <SensorTile
          label="Chuyển động"
          icon={PersonStanding}
          color={CHART_COLORS.motion}
          textValue
          value={s.motion === undefined ? "--" : s.motion ? "Có người" : "Không có người"}
          hint={!s.motion && lastMotion ? `Lần cuối ${timeAgo(lastMotion)}` : "Theo dõi chuyển động trong nhà"}
          stale={stale}
        >
          <PresenceStrip
            history={liveHistory}
            end={stripEnd}
            color={CHART_COLORS.motion}
            stale={stale}
          />
        </SensorTile>
      </div>
      </details>
    </div>
  );
}

/** Brightness fill with a marker at the firmware's dark threshold. */
function BrightnessBar({
  value,
  color,
  stale,
}: {
  value: number | undefined;
  color: string;
  stale: boolean;
}) {
  return (
    <div className="relative h-2 rounded-full bg-white/5">
      {value !== undefined && (
        <div
          className={clsx("h-full rounded-full transition-[width] duration-300", stale && "bg-slate-600")}
          style={{ width: `${value}%`, backgroundColor: stale ? undefined : color }}
        />
      )}
      <div
        className="absolute -top-1 h-4 w-0.5 -translate-x-1/2 rounded bg-slate-300"
        style={{ left: `${DARK_PERCENT}%` }}
        title={`Ngưỡng tối ${DARK_PERCENT}%`}
      />
    </div>
  );
}

/** Last 5 minutes in equal segments, filled where the PIR reported someone. */
function PresenceStrip({
  history,
  end,
  color,
  stale,
}: {
  history: LiveSample[];
  end: number;
  color: string;
  stale: boolean;
}) {
  const segmentMs = LIVE_WINDOW_MS / PRESENCE_SEGMENTS;
  const start = end - LIVE_WINDOW_MS;
  const filled = new Array<boolean>(PRESENCE_SEGMENTS).fill(false);
  for (const sample of history) {
    if (!sample.motion || sample.t < start || sample.t > end) continue;
    filled[Math.min(PRESENCE_SEGMENTS - 1, Math.floor((sample.t - start) / segmentMs))] = true;
  }

  return (
    <div>
      <div className="flex h-2 gap-0.5" aria-hidden="true">
        {filled.map((on, index) => (
          <span
            key={index}
            className={clsx("flex-1 rounded-sm", !on && "bg-white/5", on && stale && "bg-slate-600")}
            style={on && !stale ? { backgroundColor: color } : undefined}
          />
        ))}
      </div>
      <div className="mt-1 flex justify-between text-[10px] text-slate-500">
        <span>5 phút trước</span>
        <span>{stale ? "lần cuối" : "bây giờ"}</span>
      </div>
    </div>
  );
}
