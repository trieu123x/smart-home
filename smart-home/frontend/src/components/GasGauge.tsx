"use client";

import clsx from "clsx";

import { GAS_GAUGE_MAX, GAS_OFF_OFFSET, GAS_ON_OFFSET } from "@/lib/sensorLogic";

const CX = 60;
const CY = 58;
const R = 48;

/** Point on the semicircle; 0 = left end, 1 = right end. */
function point(fraction: number, radius = R) {
  const angle = Math.PI * (1 - fraction);
  return { x: CX + radius * Math.cos(angle), y: CY - radius * Math.sin(angle) };
}

function arc(from: number, to: number) {
  const a = point(from);
  const b = point(to);
  return `M ${a.x.toFixed(2)} ${a.y.toFixed(2)} A ${R} ${R} 0 0 1 ${b.x.toFixed(2)} ${b.y.toFixed(2)}`;
}

const BANDS = [
  { from: 0, to: GAS_OFF_OFFSET / GAS_GAUGE_MAX, color: "stroke-emerald-500" },
  { from: GAS_OFF_OFFSET / GAS_GAUGE_MAX, to: GAS_ON_OFFSET / GAS_GAUGE_MAX, color: "stroke-amber-500" },
  { from: GAS_ON_OFFSET / GAS_GAUGE_MAX, to: 1, color: "stroke-rose-500" },
];

interface Props {
  /** 0..1 of GAS_GAUGE_MAX above the baseline. */
  ratio: number;
  /** False without a baseline: grey track, no needle. */
  banded: boolean;
  stale?: boolean;
  className?: string;
}

/** Semicircle gauge of gas above baseline, banded at +250 (amber) and +500 (rose). */
export function GasGauge({ ratio, banded, stale = false, className }: Props) {
  const showBands = banded && !stale;
  const tip = point(ratio, R - 10);

  return (
    <svg viewBox="0 0 120 64" className={className} aria-hidden="true">
      {showBands ? (
        BANDS.map((band) => (
          <path
            key={band.color}
            d={arc(band.from, band.to)}
            fill="none"
            strokeWidth={8}
            className={clsx(band.color, "transition-colors duration-300")}
          />
        ))
      ) : (
        <path d={arc(0, 1)} fill="none" strokeWidth={8} className="stroke-slate-700" />
      )}
      {banded && (
        <g className={stale ? "text-slate-500" : "text-slate-100"}>
          <line
            x1={CX}
            y1={CY}
            x2={tip.x}
            y2={tip.y}
            stroke="currentColor"
            strokeWidth={2.5}
            strokeLinecap="round"
          />
          <circle cx={CX} cy={CY} r={4} fill="currentColor" />
        </g>
      )}
    </svg>
  );
}
