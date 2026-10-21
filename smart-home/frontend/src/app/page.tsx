"use client";

import { PersonStanding, ShieldAlert, Wifi } from "lucide-react";
import Link from "next/link";

import { ActivityChart } from "@/components/ActivityChart";
import { ActuatorPanel } from "@/components/ActuatorPanel";
import { useDashboard } from "@/components/DashboardProvider";
import { EventFeed } from "@/components/EventFeed";
import { LiveSensors } from "@/components/LiveSensors";
import { LiveStatus } from "@/components/LiveStatus";
import { ModeSwitch } from "@/components/ModeSwitch";
import { SensorChart } from "@/components/SensorChart";
import { StatCard } from "@/components/StatCard";
import { VideoSlot } from "@/components/VideoSlot";
import { timeAgo } from "@/lib/format";

export default function DashboardPage() {
  const { summary, events, series, activity, loading, error } = useDashboard();

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

  return (
    <div className="space-y-4">
      {/* Chế độ + đường truyền */}
      <div className="grid gap-4 lg:grid-cols-2">
        <ModeSwitch />
        <LiveStatus />
      </div>

      {/* Cảm biến trực tiếp từ ESP32 */}
      <LiveSensors />

      {/* Thiết bị + video */}
      <div className="grid gap-4 xl:grid-cols-3">
        <ActuatorPanel />
        <div className="xl:col-span-2">
          <VideoSlot />
        </div>
      </div>

      {/* Biểu đồ lịch sử + nhật ký */}
      <div className="grid gap-4 xl:grid-cols-3">
        <div className="xl:col-span-2">
          <SensorChart series={series} />
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

      <ActivityChart data={activity} />

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="Thiết bị online"
          value={`${summary.devices_online}/${summary.devices_total}`}
          hint={`${summary.actuators_on} thiết bị đang bật`}
          icon={Wifi}
          tone={summary.devices_online > 0 ? "good" : "warning"}
        />
        <StatCard
          label="Lượt chuyển động (24h)"
          value={String(summary.motion_last_24h)}
          hint="Cảm biến PIR"
          icon={PersonStanding}
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
        <StatCard
          label="Cảnh báo chưa xử lý"
          value={String(summary.unacknowledged_alerts)}
          icon={ShieldAlert}
          tone={summary.unacknowledged_alerts > 0 ? "warning" : "good"}
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
