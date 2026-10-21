"use client";

import clsx from "clsx";
import { Bot, Hand } from "lucide-react";
import { useEffect, useState } from "react";

import type { SystemMode } from "@/lib/types";

import { useDashboard } from "./DashboardProvider";

const OPTIONS: { value: SystemMode; label: string; icon: typeof Bot; hint: string }[] = [
  { value: "auto", label: "Tự động", icon: Bot, hint: "Thiết bị tự hoạt động theo cảm biến (logic chạy trên ESP32)." },
  { value: "manual", label: "Thủ công", icon: Hand, hint: "Thiết bị chỉ hoạt động khi bạn bật/tắt trên giao diện." },
];

/** Công tắc chế độ hoạt động của hệ thống: tự động / thủ công. */
export function ModeSwitch() {
  const { live, setMode } = useDashboard();
  const [pending, setPending] = useState<SystemMode | null>(null);
  const [error, setError] = useState<string | null>(null);

  const actual: SystemMode = live?.mode ?? "auto";
  const shown = pending ?? actual;
  const disabled = !live?.broker_ok;

  // ESP32 đã xác nhận chế độ mới -> bỏ trạng thái chờ
  useEffect(() => {
    if (pending && actual === pending) setPending(null);
  }, [actual, pending]);

  const choose = async (mode: SystemMode) => {
    if (mode === shown) return;
    setError(null);
    setPending(mode);
    try {
      await setMode(mode);
      setTimeout(() => setPending((current) => (current === mode ? null : current)), 4000);
    } catch (err) {
      setPending(null);
      setError(err instanceof Error ? err.message : "Không đổi được chế độ");
    }
  };

  return (
    <section className="card">
      <h2 className="card-title">Chế độ hoạt động</h2>
      <div className="mt-3 inline-flex rounded-xl border border-white/10 p-1">
        {OPTIONS.map(({ value, label, icon: Icon }) => (
          <button
            key={value}
            disabled={disabled}
            onClick={() => void choose(value)}
            className={clsx(
              "inline-flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition disabled:opacity-50",
              shown === value ? "bg-brand-500 text-ink-950" : "text-slate-400 hover:text-slate-200",
            )}
          >
            <Icon size={16} />
            {label}
          </button>
        ))}
      </div>
      <p className="muted mt-3">
        {pending ? "Đang chờ ESP32 xác nhận..." : OPTIONS.find((o) => o.value === shown)?.hint}
      </p>
      {error && <p className="mt-2 text-xs text-rose-400">{error}</p>}
    </section>
  );
}
