"use client";

import clsx from "clsx";
import { useCallback, useEffect, useState } from "react";
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { EventFeed } from "@/components/EventFeed";
import { api } from "@/lib/api";
import { AXIS_COLOR, CHART_COLORS, GRID_COLOR, SURFACE, tooltipStyle } from "@/lib/chartTheme";
import { METRIC_LABEL, METRIC_UNIT, formatDateTime } from "@/lib/format";
import type { LakePartition, MetricStats, RollupPoint, SmartEvent } from "@/lib/types";

const METRICS = ["temperature", "humidity", "ldr", "gas"] as const;
type Metric = (typeof METRICS)[number];

const EMPTY_TEXT = "Chưa có dữ liệu";

const digitsFor = (metric: string) => (metric === "ldr" || metric === "gas" || metric === "motion" ? 0 : 1);

const dayFormatter = new Intl.DateTimeFormat("vi-VN", { day: "2-digit", month: "2-digit" });
const formatDay = (iso: string) => dayFormatter.format(new Date(iso));

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`;
}

export default function AnalyticsPage() {
  const [metric, setMetric] = useState<Metric>("temperature");
  const [rollups, setRollups] = useState<RollupPoint[] | null>(null);
  const [stats, setStats] = useState<MetricStats[] | null>(null);
  const [anomalies, setAnomalies] = useState<SmartEvent[] | null>(null);
  const [lake, setLake] = useState<LakePartition[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadOverview = useCallback(async () => {
    try {
      const [statsData, anomalyData, lakeData] = await Promise.all([
        api.stats(24),
        api.events(20, "anomaly"),
        api.lake(),
      ]);
      setStats(statsData);
      setAnomalies(anomalyData);
      setLake(lakeData);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Không gọi được API");
    }
  }, []);

  useEffect(() => {
    void loadOverview();
  }, [loadOverview]);

  useEffect(() => {
    let cancelled = false;
    setRollups(null);
    api
      .rollups(metric, "1h", 168)
      .then((data) => {
        if (!cancelled) setRollups(data);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Không gọi được API");
      });
    return () => {
      cancelled = true;
    };
  }, [metric]);

  return (
    <div className="space-y-4">
      {error && (
        <p className="rounded-xl border border-rose-500/20 bg-rose-500/10 px-4 py-3 text-sm text-rose-200">
          {error}
        </p>
      )}

      <BandChart metric={metric} onMetric={setMetric} points={rollups} />

      <div className="grid gap-4 xl:grid-cols-2">
        <StatsTable stats={stats} />
        <section className="card">
          <h2 className="card-title">Bất thường gần đây</h2>
          <p className="muted mt-1">Trung bình 1 phút lệch quá ngưỡng z so với 24 giờ trước đó</p>
          <div className="mt-3">
            {anomalies === null ? (
              <p className="muted py-8 text-center">Đang tải...</p>
            ) : (
              <EventFeed events={anomalies} showAck emptyText="Chưa phát hiện bất thường nào" />
            )}
          </div>
        </section>
      </div>

      <LakeTable partitions={lake} />
    </div>
  );
}

function BandChart({
  metric,
  onMetric,
  points,
}: {
  metric: Metric;
  onMetric: (metric: Metric) => void;
  points: RollupPoint[] | null;
}) {
  const color = CHART_COLORS[metric];
  const unit = METRIC_UNIT[metric] ?? "";
  const digits = digitsFor(metric);
  // Recharts draws a range area from a [low, high] pair
  const data = (points ?? []).map((point) => ({
    ts: point.bucket_start,
    range: [point.min, point.max] as [number, number],
    avg: point.avg,
    min: point.min,
    max: point.max,
  }));

  return (
    <section className="card">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="card-title">{METRIC_LABEL[metric]} theo giờ, 7 ngày qua</h2>
          <p className="muted mt-1">
            Vùng mờ: thấp nhất – cao nhất mỗi giờ · Đường: trung bình (từ bảng tổng hợp 1h)
          </p>
        </div>
        <div className="flex rounded-xl border border-white/10 p-1">
          {METRICS.map((item) => (
            <button
              key={item}
              onClick={() => onMetric(item)}
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

      <div className="mt-4 h-72 w-full">
        {points === null ? (
          <Placeholder text="Đang tải..." />
        ) : data.length === 0 ? (
          <Placeholder text={EMPTY_TEXT} />
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -12 }}>
              <CartesianGrid stroke={GRID_COLOR} vertical={false} />
              <XAxis
                dataKey="ts"
                tickFormatter={formatDay}
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
                content={({ active, payload, label }) => {
                  const row = payload?.[0]?.payload as (typeof data)[number] | undefined;
                  if (!active || !row) return null;
                  return (
                    <div style={tooltipStyle} className="px-3 py-2">
                      <p className="text-slate-400">{formatDateTime(String(label))}</p>
                      <p>TB: {row.avg.toFixed(digits)}{unit}</p>
                      <p className="text-slate-400">
                        {row.min.toFixed(digits)}{unit} – {row.max.toFixed(digits)}{unit}
                      </p>
                    </div>
                  );
                }}
              />
              <Area
                type="monotone"
                dataKey="range"
                stroke="none"
                fill={color}
                fillOpacity={0.2}
                isAnimationActive={false}
                activeDot={false}
              />
              <Line
                type="monotone"
                dataKey="avg"
                stroke={color}
                strokeWidth={2}
                dot={false}
                activeDot={{ r: 4, strokeWidth: 2, stroke: SURFACE }}
                isAnimationActive={false}
              />
            </ComposedChart>
          </ResponsiveContainer>
        )}
      </div>
    </section>
  );
}

function StatsTable({ stats }: { stats: MetricStats[] | null }) {
  return (
    <section className="card overflow-x-auto p-0">
      <div className="px-5 pt-5">
        <h2 className="card-title">Thống kê 24 giờ</h2>
        <p className="muted mt-1">Tính trên dữ liệu thô trong SQLite</p>
      </div>
      {stats === null ? (
        <p className="muted py-8 text-center">Đang tải...</p>
      ) : stats.length === 0 ? (
        <p className="py-8 text-center text-sm text-slate-500">{EMPTY_TEXT}</p>
      ) : (
        <table className="mt-3 w-full min-w-[520px] text-sm">
          <thead>
            <tr className="border-b border-white/5 text-left text-xs uppercase tracking-wide text-slate-500">
              <th className="px-5 py-3 font-medium">Chỉ số</th>
              <th className="px-5 py-3 text-right font-medium">Thấp nhất</th>
              <th className="px-5 py-3 text-right font-medium">Trung bình</th>
              <th className="px-5 py-3 text-right font-medium">Cao nhất</th>
              <th className="px-5 py-3 text-right font-medium">Số mẫu</th>
              <th className="px-5 py-3 text-right font-medium">Bất thường</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-white/5">
            {stats.map((row) => {
              const unit = METRIC_UNIT[row.metric] ?? "";
              const digits = digitsFor(row.metric);
              return (
                <tr key={row.metric} className="hover:bg-white/[0.02]">
                  <td className="px-5 py-3 font-medium text-slate-200">
                    {METRIC_LABEL[row.metric] ?? row.metric}
                  </td>
                  <td className="px-5 py-3 text-right tabular-nums text-slate-300">
                    {row.min.toFixed(digits)}{unit}
                  </td>
                  <td className="px-5 py-3 text-right tabular-nums text-slate-300">
                    {row.avg.toFixed(digits)}{unit}
                  </td>
                  <td className="px-5 py-3 text-right tabular-nums text-slate-300">
                    {row.max.toFixed(digits)}{unit}
                  </td>
                  <td className="px-5 py-3 text-right tabular-nums text-slate-400">
                    {row.count.toLocaleString("vi-VN")}
                  </td>
                  <td className="px-5 py-3 text-right tabular-nums text-slate-300">
                    {row.anomalies}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </section>
  );
}

function LakeTable({ partitions }: { partitions: LakePartition[] | null }) {
  return (
    <section className="card overflow-x-auto p-0">
      <div className="px-5 pt-5">
        <h2 className="card-title">Kho dữ liệu Parquet</h2>
        <p className="muted mt-1">
          Mỗi ngày (UTC) một file <code>readings/date=YYYY-MM-DD/part-0.parquet</code>, xuất lúc 00:10 UTC
        </p>
      </div>
      {partitions === null ? (
        <p className="muted py-8 text-center">Đang tải...</p>
      ) : partitions.length === 0 ? (
        <p className="py-8 text-center text-sm text-slate-500">{EMPTY_TEXT}</p>
      ) : (
        <table className="mt-3 w-full min-w-[420px] text-sm">
          <thead>
            <tr className="border-b border-white/5 text-left text-xs uppercase tracking-wide text-slate-500">
              <th className="px-5 py-3 font-medium">Ngày</th>
              <th className="px-5 py-3 text-right font-medium">Số dòng</th>
              <th className="px-5 py-3 text-right font-medium">Dung lượng</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-white/5">
            {partitions.map((row) => (
              <tr key={row.date} className="hover:bg-white/[0.02]">
                <td className="px-5 py-3 font-medium text-slate-200">{row.date}</td>
                <td className="px-5 py-3 text-right tabular-nums text-slate-300">
                  {row.rows.toLocaleString("vi-VN")}
                </td>
                <td className="px-5 py-3 text-right tabular-nums text-slate-400">
                  {formatBytes(row.bytes)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

function Placeholder({ text }: { text: string }) {
  return (
    <div className="grid h-full place-items-center rounded-xl border border-dashed border-white/10 text-sm text-slate-500">
      {text}
    </div>
  );
}
