"use client";

import clsx from "clsx";
import { Plus, Trash2, X } from "lucide-react";
import { useState } from "react";

import { useDashboard } from "@/components/DashboardProvider";
import { api } from "@/lib/api";
import { METRIC_LABEL, METRIC_UNIT, OPERATOR_LABEL, timeAgo } from "@/lib/format";

const METRICS = ["temperature", "humidity", "lux", "motion", "fall"];
const OPERATORS = ["gt", "gte", "lt", "lte", "eq"] as const;

export default function AutomationsPage() {
  const { automations, devices, refresh, loading } = useDashboard();
  const [showForm, setShowForm] = useState(false);

  const targets = devices.filter((device) => device.kind !== "sensor");
  const sensors = devices.filter((device) => device.kind === "sensor");

  const toggleRule = async (id: number, enabled: boolean) => {
    await api.updateAutomation(id, { enabled });
    await refresh();
  };

  const removeRule = async (id: number) => {
    await api.deleteAutomation(id);
    await refresh();
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="muted max-w-xl">
          Chọn điều kiện để đèn, quạt hoặc còi báo tự bật/tắt. Thiết bị cần được bật chế độ tự động để thực hiện.
        </p>
        <button className="btn-primary" onClick={() => setShowForm((value) => !value)}>
          {showForm ? <X size={16} /> : <Plus size={16} />}
          {showForm ? "Đóng" : "Thêm quy tắc"}
        </button>
      </div>

      {showForm && (
        <RuleForm
          targets={targets}
          sensors={sensors}
          onDone={async () => {
            setShowForm(false);
            await refresh();
          }}
        />
      )}

      <div className="card overflow-x-auto p-0">
        <table className="w-full min-w-[820px] text-sm">
          <thead>
            <tr className="border-b border-white/5 text-left text-xs uppercase tracking-wide text-slate-500">
              <th className="px-5 py-3 font-medium">Tên quy tắc</th>
              <th className="px-5 py-3 font-medium">Điều kiện</th>
              <th className="px-5 py-3 font-medium">Hành động</th>
              <th className="px-5 py-3 font-medium">Tự tắt sau</th>
              <th className="px-5 py-3 font-medium">Kích hoạt gần nhất</th>
              <th className="px-5 py-3 font-medium">Bật</th>
              <th className="px-5 py-3" />
            </tr>
          </thead>
          <tbody className="divide-y divide-white/5">
            {automations.map((rule) => (
              <tr key={rule.id} className="hover:bg-white/[0.02]">
                <td className="px-5 py-3">
                  <p className="font-medium text-slate-200">{rule.name}</p>
                  <p className="muted">{rule.source_device_name ?? "Mọi cảm biến"}</p>
                </td>
                <td className="px-5 py-3 text-slate-300">
                  {METRIC_LABEL[rule.metric] ?? rule.metric} {OPERATOR_LABEL[rule.operator]}{" "}
                  {rule.threshold}
                  {METRIC_UNIT[rule.metric] ?? ""}
                </td>
                <td className="px-5 py-3">
                  <span
                    className={clsx(
                      "chip",
                      rule.action === "on"
                        ? "bg-brand-500/15 text-brand-400"
                        : "bg-slate-500/15 text-slate-300",
                    )}
                  >
                    {rule.action === "on" ? "Bật" : "Tắt"} {rule.target_device_name}
                  </span>
                </td>
                <td className="px-5 py-3 text-slate-400">
                  {rule.auto_off_seconds > 0 ? `${rule.auto_off_seconds}s` : "--"}
                </td>
                <td className="px-5 py-3 text-slate-400">{timeAgo(rule.last_triggered)}</td>
                <td className="px-5 py-3">
                  <button
                    role="switch"
                    aria-checked={rule.enabled}
                    aria-label={`Bật tắt quy tắc ${rule.name}`}
                    onClick={() => void toggleRule(rule.id, !rule.enabled)}
                    className={clsx(
                      "relative h-6 w-11 rounded-full transition",
                      rule.enabled ? "bg-brand-500" : "bg-white/10",
                    )}
                  >
                    <span
                      className={clsx(
                        "absolute top-1 h-4 w-4 rounded-full bg-white transition-all",
                        rule.enabled ? "left-6" : "left-1",
                      )}
                    />
                  </button>
                </td>
                <td className="px-5 py-3 text-right">
                  <button
                    className="rounded-lg p-2 text-slate-500 transition hover:bg-rose-500/10 hover:text-rose-400"
                    onClick={() => void removeRule(rule.id)}
                    aria-label={`Xóa quy tắc ${rule.name}`}
                  >
                    <Trash2 size={16} />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        {!loading && automations.length === 0 && (
          <p className="muted py-10 text-center">Chưa có quy tắc tự động nào</p>
        )}
      </div>
    </div>
  );
}

interface FormProps {
  targets: { id: number; name: string }[];
  sensors: { id: number; name: string }[];
  onDone: () => Promise<void>;
}

function RuleForm({ targets, sensors, onDone }: FormProps) {
  const [form, setForm] = useState({
    name: "",
    metric: "temperature",
    operator: "gt" as (typeof OPERATORS)[number],
    threshold: 30,
    target_device_id: targets[0]?.id ?? 0,
    source_device_id: "" as string | number,
    action: "on" as "on" | "off",
    auto_off_seconds: 0,
    cooldown_seconds: 10,
  });
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await api.createAutomation({
        ...form,
        threshold: Number(form.threshold),
        target_device_id: Number(form.target_device_id),
        source_device_id: form.source_device_id === "" ? null : Number(form.source_device_id),
        auto_off_seconds: Number(form.auto_off_seconds),
        cooldown_seconds: Number(form.cooldown_seconds),
      });
      await onDone();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Không lưu được quy tắc");
    } finally {
      setSaving(false);
    }
  };

  return (
    <form onSubmit={submit} className="card grid gap-3 md:grid-cols-3 xl:grid-cols-4">
      <div className="md:col-span-3 xl:col-span-2">
        <label className="muted">Tên quy tắc</label>
        <input
          required
          className="input mt-1"
          placeholder="Bật đèn bếp khi có người"
          value={form.name}
          onChange={(event) => setForm({ ...form, name: event.target.value })}
        />
      </div>

      <div>
        <label className="muted">Cảm biến theo dõi</label>
        <select
          className="input mt-1"
          value={form.source_device_id}
          onChange={(event) => setForm({ ...form, source_device_id: event.target.value })}
        >
          <option value="">Mọi cảm biến</option>
          {sensors.map((sensor) => (
            <option key={sensor.id} value={sensor.id}>
              {sensor.name}
            </option>
          ))}
        </select>
      </div>

      <div>
        <label className="muted">Chỉ số</label>
        <select
          className="input mt-1"
          value={form.metric}
          onChange={(event) => setForm({ ...form, metric: event.target.value })}
        >
          {METRICS.map((metric) => (
            <option key={metric} value={metric}>
              {METRIC_LABEL[metric] ?? metric}
            </option>
          ))}
        </select>
      </div>

      <div>
        <label className="muted">So sánh</label>
        <select
          className="input mt-1"
          value={form.operator}
          onChange={(event) =>
            setForm({ ...form, operator: event.target.value as (typeof OPERATORS)[number] })
          }
        >
          {OPERATORS.map((operator) => (
            <option key={operator} value={operator}>
              {OPERATOR_LABEL[operator]}
            </option>
          ))}
        </select>
      </div>

      <div>
        <label className="muted">Ngưỡng</label>
        <input
          type="number"
          step="0.1"
          className="input mt-1"
          value={form.threshold}
          onChange={(event) => setForm({ ...form, threshold: Number(event.target.value) })}
        />
      </div>

      <div>
        <label className="muted">Thiết bị điều khiển</label>
        <select
          className="input mt-1"
          value={form.target_device_id}
          onChange={(event) => setForm({ ...form, target_device_id: Number(event.target.value) })}
        >
          {targets.map((device) => (
            <option key={device.id} value={device.id}>
              {device.name}
            </option>
          ))}
        </select>
      </div>

      <div>
        <label className="muted">Hành động</label>
        <select
          className="input mt-1"
          value={form.action}
          onChange={(event) => setForm({ ...form, action: event.target.value as "on" | "off" })}
        >
          <option value="on">Bật</option>
          <option value="off">Tắt</option>
        </select>
      </div>

      <div>
        <label className="muted">Tự tắt sau (giây, 0 = không)</label>
        <input
          type="number"
          min={0}
          className="input mt-1"
          value={form.auto_off_seconds}
          onChange={(event) => setForm({ ...form, auto_off_seconds: Number(event.target.value) })}
        />
      </div>

      <div>
        <label className="muted">Khoảng nghỉ giữa các lần (giây)</label>
        <input
          type="number"
          min={0}
          className="input mt-1"
          value={form.cooldown_seconds}
          onChange={(event) => setForm({ ...form, cooldown_seconds: Number(event.target.value) })}
        />
      </div>

      <div className="flex items-end">
        <button className="btn-primary w-full" disabled={saving || targets.length === 0}>
          {saving ? "Đang lưu..." : "Lưu quy tắc"}
        </button>
      </div>

      {error && <p className="text-xs text-rose-400 md:col-span-3 xl:col-span-4">{error}</p>}
    </form>
  );
}
