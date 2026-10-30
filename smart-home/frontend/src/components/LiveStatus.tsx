"use client";

import clsx from "clsx";
import { Cpu, Radio } from "lucide-react";

import { useDashboard } from "./DashboardProvider";

/** Trạng thái đường truyền: server <-> MQTT broker <-> ESP32. */
export function LiveStatus() {
  const { live } = useDashboard();
  const broker = !!live?.broker_ok;
  const esp = !!live?.esp_online;

  return (
    <section className="card">
      <h2 className="card-title">Kết nối</h2>
      <div className="mt-3 space-y-3">
        <Row
          icon={<Radio size={16} />}
          label="Trung tâm kết nối"
          ok={broker}
          text={broker ? "Đã kết nối" : "Mất kết nối"}
        />
        <Row
          icon={<Cpu size={16} />}
          label="Bộ cảm biến"
          ok={esp}
          text={
            esp
              ? `Đang hoạt động · cập nhật ${live?.age?.toFixed(0) ?? 0} giây trước`
              : live?.age != null
                ? `Mất tín hiệu ${live.age.toFixed(0)} giây`
                : "Chưa nhận được dữ liệu"
          }
        />
      </div>
    </section>
  );
}

function Row({ icon, label, ok, text }: { icon: React.ReactNode; label: string; ok: boolean; text: string }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="flex items-center gap-2 text-sm text-slate-300">
        <span className="text-slate-500">{icon}</span>
        {label}
      </span>
      <span
        className={clsx(
          "chip",
          ok ? "bg-brand-500/15 text-brand-400" : "bg-rose-500/15 text-rose-300",
        )}
      >
        <span className={clsx("h-1.5 w-1.5 rounded-full", ok ? "bg-brand-400" : "bg-rose-400")} />
        {text}
      </span>
    </div>
  );
}
