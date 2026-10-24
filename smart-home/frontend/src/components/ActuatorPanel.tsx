"use client";

import clsx from "clsx";
import { Bell, Fan, Lightbulb, type LucideIcon } from "lucide-react";
import { useEffect, useState } from "react";

import { CHART_COLORS } from "@/lib/chartTheme";
import { actuatorReason } from "@/lib/sensorLogic";
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
  // Offline keeps the last state, dimmed, so it never looks like "off"
  const stale = !live?.esp_online;

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
      <div className="mt-3 grid gap-3 sm:grid-cols-3 xl:grid-cols-1">
        {ITEMS.map(({ key, label, icon: Icon }) => {
          const on = pending[key] ?? !!sensors[key];
          const color = CHART_COLORS[key];
          const reason = actuatorReason(key, { ...sensors, mode: sensors.mode ?? live?.mode });
          return (
            <div
              key={key}
              className={clsx(
                "flex flex-wrap items-center gap-3 rounded-2xl border p-4 transition-colors duration-300",
                !on && "border-white/5 bg-white/[0.03]",
                stale && "opacity-60",
              )}
              style={on ? { backgroundColor: `${color}1f`, borderColor: `${color}4d` } : undefined}
            >
              <span
                className={clsx(
                  "grid h-9 w-9 shrink-0 place-items-center rounded-xl transition-colors duration-300",
                  !on && "bg-white/5 text-slate-400",
                )}
                style={on ? { color, backgroundColor: `${color}26` } : undefined}
              >
                <Icon
                  size={18}
                  className={clsx(
                    on && !stale && key === "fan" && "animate-spin motion-reduce:animate-none",
                    on && !stale && key === "buzzer" && "animate-pulse motion-reduce:animate-none",
                  )}
                />
              </span>
              <div className="min-w-[6rem] flex-1">
                <p className="text-sm font-semibold text-white">{label}</p>
                <p className={clsx("text-xs", !on && "text-slate-400")} style={on ? { color } : undefined}>
                  {on ? "Đang bật" : "Đang tắt"}
                  {key in pending ? " · đang gửi lệnh..." : ""}
                </p>
                <p className="truncate text-xs text-slate-400">{on ? (reason ?? "—") : "—"}</p>
              </div>
              <div className="ml-auto flex rounded-xl border border-white/10 p-1">
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
