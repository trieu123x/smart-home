"use client";

import clsx from "clsx";
import { Bell, Fan, Lightbulb, type LucideIcon } from "lucide-react";
import { useEffect, useState } from "react";

import type { ControlKey } from "@/lib/types";

import { useDashboard } from "./DashboardProvider";

const ITEMS: { key: ControlKey; label: string; icon: LucideIcon }[] = [
  { key: "light", label: "Đèn", icon: Lightbulb },
  { key: "fan", label: "Quạt", icon: Fan },
  { key: "buzzer", label: "Loa", icon: Bell },
];

/** Trạng thái đèn/quạt/loa (do ESP32 báo về) và nút bật/tắt - chỉ dùng được ở chế độ thủ công. */
export function ActuatorPanel() {
  const { live, sendCommand } = useDashboard();
  const [pending, setPending] = useState<Partial<Record<ControlKey, boolean>>>({});
  const [error, setError] = useState<string | null>(null);

  const sensors = live?.sensors ?? {};
  const canControl = live?.mode === "manual" && !!live.esp_online;

  // Khi ESP32 báo đúng trạng thái đã yêu cầu thì bỏ trạng thái chờ
  useEffect(() => {
    setPending((current) => {
      const next = { ...current };
      let changed = false;
      for (const { key } of ITEMS) {
        if (key in next && next[key] === sensors[key]) {
          delete next[key];
          changed = true;
        }
      }
      return changed ? next : current;
    });
  }, [sensors.light, sensors.fan, sensors.buzzer]); // eslint-disable-line react-hooks/exhaustive-deps

  const clearPending = (key: ControlKey) =>
    setPending((current) => {
      const next = { ...current };
      delete next[key];
      return next;
    });

  const press = async (key: ControlKey, state: boolean) => {
    setError(null);
    setPending((current) => ({ ...current, [key]: state }));
    try {
      await sendCommand(key, state);
      setTimeout(() => clearPending(key), 3000);
    } catch (err) {
      clearPending(key);
      setError(err instanceof Error ? err.message : "Không gửi được lệnh");
    }
  };

  return (
    <section className="card">
      <h2 className="card-title">Thiết bị</h2>
      <div className="mt-3 divide-y divide-white/5">
        {ITEMS.map(({ key, label, icon: Icon }) => {
          const on = pending[key] ?? !!sensors[key];
          return (
            <div key={key} className="flex items-center gap-3 py-3">
              <span
                className={clsx(
                  "grid h-10 w-10 shrink-0 place-items-center rounded-xl transition",
                  on ? "bg-brand-500/15 text-brand-400" : "bg-white/5 text-slate-400",
                )}
              >
                <Icon size={18} className={key === "fan" && on ? "animate-spin" : undefined} />
              </span>
              <div className="min-w-0 flex-1">
                <p className="text-sm font-semibold text-white">{label}</p>
                <p className={clsx("text-xs", on ? "text-brand-400" : "text-slate-500")}>
                  {on ? "ĐANG BẬT" : "ĐANG TẮT"}
                  {key in pending ? " · đang gửi lệnh..." : ""}
                </p>
              </div>
              <div className="flex rounded-xl border border-white/10 p-1">
                {([true, false] as const).map((target) => (
                  <button
                    key={String(target)}
                    disabled={!canControl}
                    onClick={() => void press(key, target)}
                    className={clsx(
                      "rounded-lg px-3 py-1.5 text-xs font-medium transition disabled:cursor-not-allowed disabled:opacity-40",
                      on === target
                        ? target
                          ? "bg-brand-500 text-ink-950"
                          : "bg-white/15 text-white"
                        : "text-slate-400 hover:text-slate-200",
                    )}
                  >
                    {target ? "Bật" : "Tắt"}
                  </button>
                ))}
              </div>
            </div>
          );
        })}
      </div>
      <p className="muted mt-2">
        {canControl
          ? "Bấm Bật/Tắt để điều khiển trực tiếp."
          : live?.esp_online
            ? "Nút Bật/Tắt chỉ dùng được ở chế độ thủ công."
            : "ESP32 đang offline - chưa điều khiển được."}
      </p>
      {error && <p className="mt-2 text-xs text-rose-400">{error}</p>}
    </section>
  );
}
