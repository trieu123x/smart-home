"use client";

import { Droplets, PersonStanding, ShieldAlert, Sun, Thermometer, Wifi } from "lucide-react";
import Link from "next/link";

import { ActivityChart } from "@/components/ActivityChart";
import { useDashboard } from "@/components/DashboardProvider";
import { DeviceCard } from "@/components/DeviceCard";
import { EventFeed } from "@/components/EventFeed";
import { SensorChart } from "@/components/SensorChart";
import { StatCard } from "@/components/StatCard";
import { formatNumber, timeAgo } from "@/lib/format";

export default function DashboardPage() {
  const { summary, devices, events, series, activity, loading, error } = useDashboard();

  if (error) {
    return (
      <div className="card border-rose-500/30 bg-rose-500/5">
        <p className="text-sm font-semibold text-rose-300">Không kết nối được backend</p>
        <p className="muted mt-1">{error}</p>
        <p className="muted mt-2">
          Hãy chạy <code className="text-slate-300">uvicorn app.main:app --reload</code> trong thư mục
          backend.
        </p>
      </div>
    );
  }

  if (loading || !summary) {
    return <SkeletonGrid />;
  }

  const actuators = devices.filter((device) => device.kind !== "sensor");

  return (
    <div className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="Nhiệt độ hiện tại"
          value={formatNumber(summary.temperature, "°C")}
          hint="Cảm biến DHT11 phòng khách"
          icon={Thermometer}
        />
        <StatCard
          label="Độ ẩm"
          value={formatNumber(summary.humidity, "%", 0)}
          hint="Ngưỡng bật quạt: trên 30°C"
          icon={Droplets}
        />
        <StatCard
          label="Thiết bị online"
          value={`${summary.devices_online}/${summary.devices_total}`}
          hint={`${summary.actuators_on} thiết bị đang bật`}
          icon={Wifi}
          tone={summary.devices_online > 0 ? "good" : "warning"}
        />
        <StatCard
          label="Cảnh báo ngã (24h)"
          value={String(summary.falls_last_24h)}
          hint={
            summary.last_fall ? `Gần nhất ${timeAgo(summary.last_fall.ts)}` : "Chưa ghi nhận lần nào"
          }
          icon={ShieldAlert}
          tone={summary.falls_last_24h > 0 ? "critical" : "good"}
        />
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <div className="xl:col-span-2">
          <SensorChart series={series} />
        </div>

        <div className="card">
          <div className="flex items-center justify-between">
            <h2 className="card-title">Điều khiển nhanh</h2>
            <Link href="/devices" className="muted hover:text-slate-300">
              Xem tất cả
            </Link>
          </div>
          <div className="mt-3 space-y-3">
            {actuators.slice(0, 3).map((device) => (
              <DeviceCard key={device.id} device={device} />
            ))}
            {actuators.length === 0 && (
              <p className="muted py-6 text-center">Chưa có thiết bị điều khiển nào</p>
            )}
          </div>
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <div className="xl:col-span-2">
          <ActivityChart data={activity} />
        </div>

        <div className="card">
          <div className="flex items-center justify-between">
            <h2 className="card-title">Sự kiện gần đây</h2>
            <Link href="/events" className="muted hover:text-slate-300">
              Xem tất cả
            </Link>
          </div>
          <div className="mt-1 max-h-[22rem] overflow-y-auto pr-1">
            <EventFeed events={events.slice(0, 12)} />
          </div>
        </div>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="Lượt chuyển động (24h)"
          value={String(summary.motion_last_24h)}
          hint="Cảm biến PIR"
          icon={PersonStanding}
        />
        <StatCard
          label="Ánh sáng"
          value={formatNumber(summary.lux, " lux", 0)}
          hint="Dưới 80 lux sẽ bật đèn hành lang"
          icon={Sun}
        />
        <StatCard
          label="Cảnh báo chưa xử lý"
          value={String(summary.unacknowledged_alerts)}
          icon={ShieldAlert}
          tone={summary.unacknowledged_alerts > 0 ? "warning" : "good"}
        />
        <StatCard
          label="Thiết bị đang bật"
          value={String(summary.actuators_on)}
          hint="Quạt, đèn, còi báo"
          icon={Wifi}
        />
      </div>
    </div>
  );
}

function SkeletonGrid() {
  return (
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      {Array.from({ length: 8 }).map((_, index) => (
        <div key={index} className="card h-28 animate-pulse bg-ink-900/60" />
      ))}
    </div>
  );
}
