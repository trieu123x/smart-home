"use client";

import { AlertTriangle, Check } from "lucide-react";

import { timeAgo } from "@/lib/format";

import { useDashboard } from "./DashboardProvider";

/** Dải cảnh báo đỏ hiện ngay dưới thanh tiêu đề khi có người ngã chưa xử lý. */
export function FallAlertBanner() {
  const { activeFall, ackEvent } = useDashboard();

  if (!activeFall) return null;

  return (
    <div className="mx-4 mt-4 flex flex-wrap items-center gap-3 rounded-2xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 sm:mx-6 lg:mx-8">
      <span className="grid h-10 w-10 shrink-0 animate-pulse place-items-center rounded-xl bg-rose-500/20 text-rose-300">
        <AlertTriangle size={20} />
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-semibold text-rose-200">PHÁT HIỆN NGÃ</p>
        <p className="truncate text-xs text-rose-200/80">
          {activeFall.message} · {timeAgo(activeFall.ts)}
        </p>
      </div>
      <button
        className="btn bg-rose-500 text-white hover:bg-rose-400"
        onClick={() => void ackEvent(activeFall.id)}
      >
        <Check size={16} />
        Đã xử lý
      </button>
    </div>
  );
}
