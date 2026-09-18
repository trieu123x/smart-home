"use client";

import clsx from "clsx";
import { Activity, Bell, Home, LayoutDashboard, Plug, Workflow } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { useDashboard } from "./DashboardProvider";

const NAV = [
  { href: "/", label: "Tổng quan", icon: LayoutDashboard },
  { href: "/devices", label: "Thiết bị", icon: Plug },
  { href: "/automations", label: "Tự động hóa", icon: Workflow },
  { href: "/events", label: "Cảnh báo", icon: Bell },
];

export function Sidebar() {
  const pathname = usePathname();
  const { summary, connected } = useDashboard();

  return (
    <aside className="sticky top-0 hidden h-screen w-64 shrink-0 flex-col border-r border-white/5 bg-ink-900 p-5 lg:flex">
      <div className="flex items-center gap-3 px-1">
        <span className="grid h-10 w-10 place-items-center rounded-xl bg-brand-500/15 text-brand-400">
          <Home size={20} />
        </span>
        <div>
          <p className="text-sm font-semibold text-white">Smart Home</p>
          <p className="muted">Đồ án IoT · ESP32</p>
        </div>
      </div>

      <nav className="mt-8 space-y-1">
        {NAV.map(({ href, label, icon: Icon }) => {
          const active = pathname === href;
          return (
            <Link
              key={href}
              href={href}
              className={clsx(
                "flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition",
                active
                  ? "bg-brand-500/15 text-brand-400"
                  : "text-slate-400 hover:bg-white/5 hover:text-slate-200",
              )}
            >
              <Icon size={18} />
              {label}
              {href === "/events" && summary && summary.unacknowledged_alerts > 0 && (
                <span className="ml-auto rounded-full bg-rose-500/20 px-2 py-0.5 text-[11px] font-semibold text-rose-300">
                  {summary.unacknowledged_alerts}
                </span>
              )}
            </Link>
          );
        })}
      </nav>

      <div className="mt-auto rounded-xl border border-white/5 bg-ink-800 p-4">
        <div className="flex items-center gap-2 text-xs font-medium text-slate-300">
          <Activity size={14} className={connected ? "text-brand-400" : "text-slate-500"} />
          {connected ? "Đang nhận dữ liệu realtime" : "Mất kết nối realtime"}
        </div>
        <p className="muted mt-2">
          {summary ? `${summary.devices_online}/${summary.devices_total} thiết bị online` : "Đang tải..."}
        </p>
      </div>
    </aside>
  );
}
