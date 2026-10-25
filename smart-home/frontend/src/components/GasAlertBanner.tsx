"use client";

import { Flame } from "lucide-react";

import { useDashboard } from "./DashboardProvider";

/** Dải cảnh báo đỏ khi cảm biến MQ-2 báo gas/khói (tự mất khi hết nguy hiểm). */
export function GasAlertBanner() {
  const { live } = useDashboard();

  if (!live?.esp_online || !live.sensors.gas_alarm) return null;

  const gas = Math.round(live.sensors.gas ?? 0);
  const base = Number.isFinite(live.sensors.gas_base) ? live.sensors.gas_base : undefined;

  return (
    <div className="mx-4 mt-4 flex flex-wrap items-center gap-3 rounded-2xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 sm:mx-6 lg:mx-8">
      <span className="grid h-10 w-10 shrink-0 animate-pulse place-items-center rounded-xl bg-rose-500/20 text-rose-300">
        <Flame size={20} />
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-semibold text-rose-200">PHÁT HIỆN GAS/KHÓI</p>
        <p className="truncate text-xs text-rose-200/80">
          {base === undefined
            ? `Nồng độ hiện tại (ADC): ${gas} · quạt xả gas và loa báo động đang hoạt động`
            : `Nồng độ (ADC): ${gas} · vượt nền +${gas - Math.round(base)}`}
        </p>
      </div>
    </div>
  );
}
