"use client";

import { CheckCheck } from "lucide-react";
import { useMemo, useState } from "react";

import { useDashboard } from "@/components/DashboardProvider";
import { EventFeed } from "@/components/EventFeed";
import { EVENT_LABEL } from "@/lib/format";

const FILTERS = [
  { value: "all", label: "Tất cả" },
  { value: "fall_detected", label: EVENT_LABEL.fall_detected },
  { value: "motion", label: EVENT_LABEL.motion },
  { value: "automation", label: EVENT_LABEL.automation },
  { value: "manual", label: EVENT_LABEL.manual },
];

export default function EventsPage() {
  const { events, ackAll, summary, loading } = useDashboard();
  const [filter, setFilter] = useState("all");

  const filtered = useMemo(
    () => (filter === "all" ? events : events.filter((event) => event.type === filter)),
    [events, filter],
  );

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap gap-2">
          {FILTERS.map((option) => (
            <button
              key={option.value}
              onClick={() => setFilter(option.value)}
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

        <button
          className="btn-ghost"
          onClick={() => void ackAll()}
          disabled={!summary || summary.unacknowledged_alerts === 0}
        >
          <CheckCheck size={16} />
          Xác nhận tất cả
        </button>
      </div>

      <div className="card">
        {loading ? (
          <p className="muted py-8 text-center">Đang tải nhật ký...</p>
        ) : (
          <EventFeed events={filtered} showAck emptyText="Không có sự kiện nào thuộc nhóm này" />
        )}
      </div>
    </div>
  );
}
