"use client";

import clsx from "clsx";
import {
  Moon,
  Power,
  ShieldAlert,
  ShieldCheck,
  Sun,
  Thermometer,
  WifiOff,
  type LucideIcon,
} from "lucide-react";

import { LDR_DARK_THRESHOLD, brightnessPercent, comfortLabel } from "@/lib/sensorLogic";
import type { LiveSensors } from "@/lib/types";

import { useDashboard } from "./DashboardProvider";
import { TONES } from "./StatCard";

type Accent = "brand" | "amber" | "rose";

const ACCENTS: Record<Accent, { border: string; icon: string }> = {
  brand: { border: "border-l-brand-500", icon: TONES.good.icon },
  amber: { border: "border-l-amber-500", icon: TONES.warning.icon },
  rose: { border: "border-l-rose-500", icon: TONES.critical.icon },
};

const num = (value: unknown) =>
  typeof value === "number" && Number.isFinite(value) ? value : undefined;

/** "12s trước" for short gaps, minutes once it has been gone a while. */
function formatAge(seconds: number) {
  const s = Math.max(0, Math.floor(seconds));
  return s < 120 ? `${s}s trước` : `${Math.floor(s / 60)} phút trước`;
}

interface Props {
  sensors: LiveSensors;
  /** Values are the last known ones, not live. */
  stale: boolean;
  /** Seconds since the last ESP32 message, ticking locally; null when nothing was ever received. */
  age: number | null;
}

/** Apple-Home-style row: safety, climate, light and devices at a glance. */
export function HomeSummary({ sensors: s, stale, age }: Props) {
  const { live } = useDashboard();
  const mode = live?.mode ?? s.mode;
  const temp = num(s.temp);
  const hum = num(s.hum);
  const ldr = num(s.ldr);
  const hasData = Object.keys(s).length > 0;

  const gasDanger = !!s.gas_alarm;
  const comfort = temp !== undefined && hum !== undefined ? comfortLabel(temp, hum) : undefined;
  const dark = s.dark ?? (ldr !== undefined ? ldr > LDR_DARK_THRESHOLD : undefined);
  const onCount = (["light", "fan", "buzzer"] as const).filter((key) => s[key]).length;

  return (
    <div className="space-y-3">
      {stale && (
        <div className="flex w-full items-center gap-2 rounded-xl border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs font-medium text-rose-300">
          <WifiOff size={14} className="shrink-0" />
          {age === null || !hasData
            ? "Chưa nhận được dữ liệu"
            : `Mất tín hiệu · ${formatAge(age)}`}
        </div>
      )}

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <SummaryTile
          title="An toàn"
          icon={gasDanger ? ShieldAlert : ShieldCheck}
          pulse={gasDanger}
          accent={gasDanger ? "rose" : "brand"}
          stale={stale}
          line1={!hasData ? "--" : gasDanger ? "PHÁT HIỆN GAS" : "Không có gas"}
          line2={s.motion === undefined ? "--" : s.motion ? "Có người" : "Không có người"}
        />
        <SummaryTile
          title="Khí hậu"
          icon={Thermometer}
          accent={comfort === "Nóng" || comfort === "Nóng ẩm" || comfort === "Lạnh" ? "amber" : "brand"}
          stale={stale}
          line1={
            temp === undefined && hum === undefined
              ? "--"
              : `${temp === undefined ? "--" : temp.toFixed(1)}° · ${hum === undefined ? "--" : Math.round(hum)}%`
          }
          line2={comfort ?? "--"}
        />
        <SummaryTile
          title="Ánh sáng"
          icon={dark ? Moon : Sun}
          accent={dark && !s.light && s.motion ? "amber" : "brand"}
          stale={stale}
          line1={
            ldr === undefined
              ? "--"
              : `${dark ? "Tối" : "Sáng"} · ${brightnessPercent(ldr)}%`
          }
          line2={s.light === undefined ? "--" : s.light ? "Đèn bật" : "Đèn tắt"}
        />
        <SummaryTile
          title="Thiết bị"
          icon={Power}
          accent="brand"
          stale={stale}
          line1={hasData ? `${onCount}/3 đang bật` : "--"}
          line2={mode === "manual" ? "Thủ công" : "Tự động"}
        />
      </div>
    </div>
  );
}

function SummaryTile({
  title,
  icon: Icon,
  accent,
  stale,
  pulse = false,
  line1,
  line2,
}: {
  title: string;
  icon: LucideIcon;
  accent: Accent;
  stale: boolean;
  pulse?: boolean;
  line1: string;
  line2: string;
}) {
  const styles = ACCENTS[accent];
  return (
    <div
      className={clsx(
        "card min-w-0 border-l-2 transition-colors duration-300",
        stale ? "border-l-slate-600 opacity-60" : styles.border,
      )}
    >
      <div className="flex items-center gap-3">
        <span
          className={clsx(
            "grid h-9 w-9 shrink-0 place-items-center rounded-xl transition-colors duration-300",
            stale ? TONES.default.icon : styles.icon,
          )}
        >
          <Icon
            size={18}
            className={pulse && !stale ? "animate-pulse motion-reduce:animate-none" : undefined}
          />
        </span>
        <p className="card-title truncate">{title}</p>
      </div>
      <p className="mt-3 text-sm font-semibold tabular-nums text-white">{line1}</p>
      <p className="mt-0.5 text-xs text-slate-400">{line2}</p>
    </div>
  );
}
