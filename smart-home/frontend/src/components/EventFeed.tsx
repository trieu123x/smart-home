"use client";

import clsx from "clsx";
import {
  Activity,
  AlertTriangle,
  Check,
  Flame,
  Hand,
  PersonStanding,
  Plug,
  PlugZap,
  Zap,
  type LucideIcon,
} from "lucide-react";

import { EVENT_LABEL, timeAgo } from "@/lib/format";
import type { SmartEvent } from "@/lib/types";

import { useDashboard } from "./DashboardProvider";

const ICONS: Record<string, LucideIcon> = {
  fall_detected: AlertTriangle,
  motion: PersonStanding,
  gas_alarm: Flame,
  gas_clear: Flame,
  automation: Zap,
  manual: Hand,
  device_online: PlugZap,
  device_offline: Plug,
  anomaly: Activity,
};

const SEVERITY_STYLE: Record<string, string> = {
  info: "bg-white/5 text-slate-300",
  warning: "bg-amber-500/15 text-amber-400",
  critical: "bg-rose-500/15 text-rose-400",
};

interface Props {
  events: SmartEvent[];
  /** Hiện nút "đã xử lý" cho các cảnh báo chưa được xác nhận. */
  showAck?: boolean;
  emptyText?: string;
}

export function EventFeed({ events, showAck = false, emptyText = "Chưa có sự kiện nào" }: Props) {
  const { ackEvent } = useDashboard();

  if (events.length === 0) {
    return <p className="py-8 text-center text-sm text-slate-500">{emptyText}</p>;
  }

  return (
    <ul className="divide-y divide-white/5">
      {events.map((event) => {
        const Icon = ICONS[event.type] ?? Zap;
        return (
          <li key={event.id} className="flex items-start gap-3 py-3">
            <span
              className={clsx(
                "mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-lg",
                SEVERITY_STYLE[event.severity],
              )}
            >
              <Icon size={15} />
            </span>

            <div className="min-w-0 flex-1">
              <p className="text-sm text-slate-200">{event.message}</p>
              <p className="muted mt-0.5">
                {EVENT_LABEL[event.type] ?? event.type}
                {event.device_name ? ` · ${event.device_name}` : ""} · {timeAgo(event.ts)}
              </p>
            </div>

            {showAck && !event.acknowledged && event.severity !== "info" && (
              <button
                className="btn-ghost shrink-0 !px-2.5 !py-1.5 text-xs"
                onClick={() => void ackEvent(event.id)}
              >
                <Check size={14} />
                Đã xử lý
              </button>
            )}
          </li>
        );
      })}
    </ul>
  );
}
