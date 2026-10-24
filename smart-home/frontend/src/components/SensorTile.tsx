"use client";

import clsx from "clsx";
import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import { Sparkline } from "./Sparkline";
import { TONES, type Tone } from "./StatCard";

interface Props {
  label: string;
  value: string;
  unit?: string;
  hint?: string;
  icon: LucideIcon;
  /** Sensor identity colour (CHART_COLORS), used for the icon and the sparkline. */
  color: string;
  badge?: { text: string; tone: Tone };
  /** Text values ("Không có người") use a smaller size so they fit five tiles per row. */
  textValue?: boolean;
  /** Last values kept while the ESP32 is offline: dimmed and greyed. */
  stale?: boolean;
  trend?: (number | undefined)[];
  trendMin?: number;
  trendMax?: number;
  iconClassName?: string;
  children?: ReactNode;
}

/** Live sensor tile: value, derived label and a sparkline along the bottom edge. */
export function SensorTile({
  label,
  value,
  unit,
  hint,
  icon: Icon,
  color,
  badge,
  textValue = false,
  stale = false,
  trend,
  trendMin,
  trendMax,
  iconClassName,
  children,
}: Props) {
  const showUnit = unit && value !== "--";
  return (
    <div
      className={clsx(
        "card flex min-w-0 flex-col overflow-hidden transition-opacity duration-300",
        stale && "opacity-60",
      )}
    >
      <div className="flex items-center gap-3">
        <span
          className="grid h-9 w-9 shrink-0 place-items-center rounded-xl"
          style={{ color, backgroundColor: `${color}26` }}
        >
          <Icon size={18} className={iconClassName} />
        </span>
        <p className="muted min-w-0 flex-1 truncate">{label}</p>
        {badge && (
          <span
            className={clsx(
              "chip shrink-0 transition-colors duration-300",
              TONES[stale ? "default" : badge.tone].icon,
            )}
          >
            {badge.text}
          </span>
        )}
      </div>

      <p
        className={clsx(
          "mt-3 font-semibold tabular-nums leading-tight text-white",
          textValue ? "text-2xl" : "text-3xl",
        )}
      >
        {value}
        {showUnit && <span className="ml-1 text-base font-normal text-slate-400">{unit}</span>}
      </p>
      {hint && <p className="mt-1 truncate text-xs text-slate-400">{hint}</p>}

      {children && <div className="mt-3">{children}</div>}

      <div className="mt-auto pt-3">
        <div
          className={clsx("-mx-5 -mb-5 h-8", stale && "text-slate-600")}
          style={stale ? undefined : { color }}
        >
          {trend && (
            <Sparkline values={trend} min={trendMin} max={trendMax} className="h-full w-full" />
          )}
        </div>
      </div>
    </div>
  );
}
