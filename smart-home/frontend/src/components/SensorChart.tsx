"use client";

import clsx from "clsx";
import { useState } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { AXIS_COLOR, CHART_COLORS, GRID_COLOR, SURFACE, tooltipStyle } from "@/lib/chartTheme";
import { METRIC_LABEL, METRIC_UNIT, formatDateTime, formatTime } from "@/lib/format";
import type { MetricSeries } from "@/lib/types";

const METRICS = ["temperature", "humidity", "ldr", "gas"] as const;
type Metric = (typeof METRICS)[number];

/**
 * Nhiệt độ, độ ẩm và ánh sáng có thang đo khác nhau nên không vẽ chung một trục -
 * người dùng chọn từng chỉ số, biểu đồ luôn chỉ có một đường.
 */
export function SensorChart({ series }: { series: MetricSeries[] }) {
  const [metric, setMetric] = useState<Metric>("temperature");

  const color = CHART_COLORS[metric];
  const unit = METRIC_UNIT[metric];
  const digits = metric === "ldr" || metric === "gas" ? 0 : 1; // ADC là số nguyên
  const points = series.find((line) => line.metric === metric)?.points ?? [];
  const data = points.map((point) => ({ ts: point.ts, value: point.value }));
  const latest = data.at(-1)?.value;

  return (
    <section className="card">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="card-title">{METRIC_LABEL[metric]} trong 12 giờ qua</h2>
          <p className="muted mt-1">Thông tin ghi nhận từ các cảm biến trong nhà</p>
        </div>
        <div className="flex rounded-xl border border-white/10 p-1">
          {METRICS.map((item) => (
            <button
              key={item}
              onClick={() => setMetric(item)}
              className={clsx(
                "rounded-lg px-3 py-1.5 text-xs font-medium transition",
                metric === item ? "bg-white/10 text-white" : "text-slate-400 hover:text-slate-200",
              )}
            >
              {METRIC_LABEL[item]}
            </button>
          ))}
        </div>
      </div>

      <p className="mt-4 text-3xl font-semibold text-white">
        {latest === undefined ? "--" : latest.toFixed(digits)}
        <span className="ml-1 text-base font-normal text-slate-400">{unit}</span>
      </p>

      <div className="mt-2 h-64 w-full">
        {data.length === 0 ? (
          <EmptyChart />
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -12 }}>
              <defs>
                <linearGradient id={`fill-${metric}`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={color} stopOpacity={0.35} />
                  <stop offset="100%" stopColor={color} stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid stroke={GRID_COLOR} vertical={false} />
              <XAxis
                dataKey="ts"
                tickFormatter={formatTime}
                tick={{ fill: AXIS_COLOR, fontSize: 11 }}
                tickLine={false}
                axisLine={false}
                minTickGap={40}
              />
              <YAxis
                width={56}
                tick={{ fill: AXIS_COLOR, fontSize: 11 }}
                tickLine={false}
                axisLine={false}
                domain={["auto", "auto"]}
                tickFormatter={(value: number) => `${value}${unit}`}
              />
              <Tooltip
                contentStyle={tooltipStyle}
                cursor={{ stroke: color, strokeWidth: 1, strokeDasharray: "4 4" }}
                labelFormatter={(value: string) => formatDateTime(value)}
                formatter={(value: number) => [`${value.toFixed(digits)}${unit}`, METRIC_LABEL[metric]]}
              />
              <Area
                type="monotone"
                dataKey="value"
                stroke={color}
                strokeWidth={2}
                fill={`url(#fill-${metric})`}
                activeDot={{ r: 4, strokeWidth: 2, stroke: SURFACE }}
                isAnimationActive={false}
              />
            </AreaChart>
          </ResponsiveContainer>
        )}
      </div>
    </section>
  );
}

function EmptyChart() {
  return (
    <div className="grid h-full place-items-center rounded-xl border border-dashed border-white/10 text-sm text-slate-500">
      Chưa có dữ liệu - hãy chạy simulator hoặc cắm thiết bị
    </div>
  );
}
