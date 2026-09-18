"use client";

import { AlertTriangle, PersonStanding, Zap } from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { AXIS_COLOR, CHART_COLORS, GRID_COLOR, tooltipStyle } from "@/lib/chartTheme";
import type { ActivityBucket } from "@/lib/types";

const SERIES = [
  { key: "motion", label: "Chuyển động", color: CHART_COLORS.motion, icon: PersonStanding },
  { key: "automation", label: "Tự động hóa", color: CHART_COLORS.automation, icon: Zap },
  { key: "fall", label: "Phát hiện ngã", color: CHART_COLORS.fall, icon: AlertTriangle },
] as const;

const hourLabel = (value: string) => `${value.slice(11, 13)}h`;

/** Số sự kiện theo từng giờ trong 24 giờ qua. */
export function ActivityChart({ data }: { data: ActivityBucket[] }) {
  return (
    <section className="card">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="card-title">Hoạt động 24 giờ qua</h2>
          <p className="muted mt-1">Số sự kiện ghi nhận theo từng giờ</p>
        </div>
        {/* Chú giải kèm biểu tượng - không phân biệt bằng riêng màu sắc */}
        <ul className="flex flex-wrap gap-3">
          {SERIES.map(({ key, label, color, icon: Icon }) => (
            <li key={key} className="flex items-center gap-1.5 text-xs text-slate-400">
              <Icon size={13} style={{ color }} />
              <span className="h-2 w-2 rounded-sm" style={{ backgroundColor: color }} />
              {label}
            </li>
          ))}
        </ul>
      </div>

      <div className="mt-4 h-56 w-full">
        {data.length === 0 ? (
          <div className="grid h-full place-items-center rounded-xl border border-dashed border-white/10 text-sm text-slate-500">
            Chưa có sự kiện nào trong 24 giờ qua
          </div>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -20 }} barGap={2}>
              <CartesianGrid stroke={GRID_COLOR} vertical={false} />
              <XAxis
                dataKey="hour"
                tickFormatter={hourLabel}
                tick={{ fill: AXIS_COLOR, fontSize: 11 }}
                tickLine={false}
                axisLine={false}
                minTickGap={16}
              />
              <YAxis
                width={44}
                allowDecimals={false}
                tick={{ fill: AXIS_COLOR, fontSize: 11 }}
                tickLine={false}
                axisLine={false}
              />
              <Tooltip
                contentStyle={tooltipStyle}
                cursor={{ fill: "rgba(148,163,184,0.08)" }}
                labelFormatter={(value: string) => `Khung giờ ${hourLabel(value)}`}
              />
              {SERIES.map(({ key, label, color }) => (
                <Bar
                  key={key}
                  dataKey={key}
                  name={label}
                  fill={color}
                  radius={[4, 4, 0, 0]}
                  maxBarSize={10}
                  isAnimationActive={false}
                />
              ))}
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>
    </section>
  );
}
