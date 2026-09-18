"use client";

import { Plus, X } from "lucide-react";
import { useMemo, useState } from "react";

import { useDashboard } from "@/components/DashboardProvider";
import { DeviceCard } from "@/components/DeviceCard";
import { api } from "@/lib/api";
import type { DeviceKind } from "@/lib/types";

const KIND_OPTIONS: { value: DeviceKind; label: string }[] = [
  { value: "sensor", label: "Cảm biến" },
  { value: "fan", label: "Quạt" },
  { value: "light", label: "Đèn" },
  { value: "alarm", label: "Còi báo" },
];

export default function DevicesPage() {
  const { devices, refresh, loading } = useDashboard();
  const [showForm, setShowForm] = useState(false);
  const [filter, setFilter] = useState<"all" | DeviceKind>("all");

  const rooms = useMemo(() => {
    const grouped = new Map<string, typeof devices>();
    for (const device of devices) {
      if (filter !== "all" && device.kind !== filter) continue;
      grouped.set(device.room, [...(grouped.get(device.room) ?? []), device]);
    }
    return [...grouped.entries()];
  }, [devices, filter]);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap gap-2">
          {[{ value: "all", label: "Tất cả" }, ...KIND_OPTIONS].map((option) => (
            <button
              key={option.value}
              onClick={() => setFilter(option.value as "all" | DeviceKind)}
              className={
                filter === option.value
                  ? "chip bg-brand-500/15 text-brand-400"
                  : "chip border border-white/10 text-slate-400 hover:text-slate-200"
              }
            >
              {option.label}
            </button>
          ))}
        </div>

        <button className="btn-primary" onClick={() => setShowForm((value) => !value)}>
          {showForm ? <X size={16} /> : <Plus size={16} />}
          {showForm ? "Đóng" : "Thêm thiết bị"}
        </button>
      </div>

      {showForm && <DeviceForm onDone={async () => { setShowForm(false); await refresh(); }} />}

      {loading && <p className="muted">Đang tải danh sách thiết bị...</p>}

      {rooms.map(([room, items]) => (
        <section key={room} className="space-y-3">
          <h2 className="text-sm font-semibold text-slate-300">{room}</h2>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {items.map((device) => (
              <DeviceCard key={device.id} device={device} />
            ))}
          </div>
        </section>
      ))}

      {!loading && rooms.length === 0 && (
        <p className="muted py-10 text-center">Không có thiết bị nào khớp bộ lọc</p>
      )}
    </div>
  );
}

function DeviceForm({ onDone }: { onDone: () => Promise<void> }) {
  const [form, setForm] = useState({ code: "", name: "", kind: "sensor" as DeviceKind, room: "" });
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await api.createDevice({ ...form, room: form.room || "Chung" });
      await onDone();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Không lưu được thiết bị");
    } finally {
      setSaving(false);
    }
  };

  return (
    <form onSubmit={submit} className="card grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
      <div>
        <label className="muted">Mã thiết bị (trùng với firmware)</label>
        <input
          required
          className="input mt-1"
          placeholder="esp32-phongbep"
          value={form.code}
          onChange={(event) => setForm({ ...form, code: event.target.value })}
        />
      </div>
      <div>
        <label className="muted">Tên hiển thị</label>
        <input
          required
          className="input mt-1"
          placeholder="Cảm biến phòng bếp"
          value={form.name}
          onChange={(event) => setForm({ ...form, name: event.target.value })}
        />
      </div>
      <div>
        <label className="muted">Loại</label>
        <select
          className="input mt-1"
          value={form.kind}
          onChange={(event) => setForm({ ...form, kind: event.target.value as DeviceKind })}
        >
          {KIND_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </div>
      <div>
        <label className="muted">Phòng</label>
        <input
          className="input mt-1"
          placeholder="Phòng bếp"
          value={form.room}
          onChange={(event) => setForm({ ...form, room: event.target.value })}
        />
      </div>
      <div className="flex items-end">
        <button className="btn-primary w-full" disabled={saving}>
          {saving ? "Đang lưu..." : "Lưu thiết bị"}
        </button>
      </div>
      {error && <p className="text-xs text-rose-400 sm:col-span-2 xl:col-span-5">{error}</p>}
    </form>
  );
}
