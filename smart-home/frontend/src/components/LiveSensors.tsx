"use client";

import { Droplets, Flame, PersonStanding, Sun, Thermometer } from "lucide-react";

import { formatNumber } from "@/lib/format";

import { useDashboard } from "./DashboardProvider";
import { StatCard } from "./StatCard";

/** Hàng thẻ cảm biến cập nhật theo từng bản tin MQTT của ESP32. */
export function LiveSensors() {
  const { live } = useDashboard();
  const s = live?.sensors ?? {};
  const online = !!live?.esp_online;
  const dash = (value: string) => (online ? value : "--");

  return (
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
      <StatCard
        label="Nhiệt độ"
        value={dash(formatNumber(s.temp, "°C"))}
        hint="DHT22"
        icon={Thermometer}
      />
      <StatCard
        label="Độ ẩm"
        value={dash(formatNumber(s.hum, "%", 0))}
        hint="DHT22"
        icon={Droplets}
      />
      <StatCard
        label="Độ sáng (LDR)"
        value={dash(s.ldr === undefined ? "--" : String(Math.round(s.ldr)))}
        hint={online && s.dark !== undefined ? (s.dark ? "Trời tối" : "Trời sáng") : "ADC"}
        icon={Sun}
        tone={online && s.dark ? "warning" : "default"}
      />
      <StatCard
        label="Gas/khói (ADC)"
        value={dash(s.gas === undefined ? "--" : String(Math.round(s.gas)))}
        hint={online && s.gas_alarm ? "NGUY HIỂM" : "MQ-2 · bình thường"}
        icon={Flame}
        tone={online && s.gas_alarm ? "critical" : "default"}
      />
      <StatCard
        label="Chuyển động"
        value={dash(s.motion === undefined ? "--" : s.motion ? "Có người" : "Không có")}
        hint="Cảm biến PIR"
        icon={PersonStanding}
        tone={online && s.motion ? "warning" : "default"}
      />
    </div>
  );
}
