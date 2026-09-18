"use client";

import clsx from "clsx";
import { Bell, Fan, Lightbulb, Radar } from "lucide-react";
import { useState } from "react";

import { timeAgo } from "@/lib/format";
import type { Device } from "@/lib/types";

import { useDashboard } from "./DashboardProvider";

const ICONS = {
  sensor: Radar,
  fan: Fan,
  light: Lightbulb,
  alarm: Bell,
} as const;

const KIND_LABEL = {
  sensor: "Cảm biến",
  fan: "Quạt",
  light: "Đèn",
  alarm: "Còi báo",
} as const;

export function DeviceCard({ device }: { device: Device }) {
  const { toggleDevice, setAutoMode } = useDashboard();
  const [busy, setBusy] = useState(false);

  const Icon = ICONS[device.kind];
  const isActuator = device.kind !== "sensor";

  const handleToggle = async () => {
    setBusy(true);
    try {
      await toggleDevice(device, !device.state);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card">
      <div className="flex items-start gap-3">
        <span
          className={clsx(
            "grid h-11 w-11 shrink-0 place-items-center rounded-xl transition",
            device.state ? "bg-brand-500/15 text-brand-400" : "bg-white/5 text-slate-400",
          )}
        >
          <Icon size={20} className={device.kind === "fan" && device.state ? "animate-spin" : undefined} />
        </span>

        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold text-white">{device.name}</p>
          <p className="muted truncate">
            {KIND_LABEL[device.kind]} · {device.room}
          </p>
        </div>

        <span
          className={clsx(
            "chip shrink-0",
            device.online ? "bg-brand-500/15 text-brand-400" : "bg-slate-500/15 text-slate-400",
          )}
        >
          <span
            className={clsx(
              "h-1.5 w-1.5 rounded-full",
              device.online ? "bg-brand-400" : "bg-slate-500",
            )}
          />
          {device.online ? "Online" : "Offline"}
        </span>
      </div>

      <div className="mt-4 flex items-center justify-between gap-3">
        <p className="muted">Cập nhật {timeAgo(device.last_seen)}</p>

        {isActuator ? (
          <div className="flex items-center gap-2">
            <button
              onClick={() => void setAutoMode(device, !device.auto_mode)}
              className={clsx(
                "chip border transition",
                device.auto_mode
                  ? "border-brand-500/30 bg-brand-500/10 text-brand-400"
                  : "border-white/10 text-slate-400",
              )}
              title="Cho phép các luật tự động điều khiển thiết bị này"
            >
              AUTO
            </button>

            <button
              role="switch"
              aria-checked={device.state}
              aria-label={`Bật tắt ${device.name}`}
              disabled={busy}
              onClick={handleToggle}
              className={clsx(
                "relative h-7 w-12 rounded-full transition disabled:opacity-50",
                device.state ? "bg-brand-500" : "bg-white/10",
              )}
            >
              <span
                className={clsx(
                  "absolute top-1 h-5 w-5 rounded-full bg-white transition-all",
                  device.state ? "left-6" : "left-1",
                )}
              />
            </button>
          </div>
        ) : (
          <span className="muted">Chỉ đọc dữ liệu</span>
        )}
      </div>
    </div>
  );
}
