"use client";

import clsx from "clsx";
import { Bell, LogOut, RefreshCw, Settings2, Wifi, WifiOff } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";

import { useDashboard } from "./DashboardProvider";
import { useSession } from "./DashboardSession";
import { QuickActions } from "./QuickActions";

const TITLES: Record<string, { title: string; subtitle: string }> = {
  "/": { title: "Tổng quan ngôi nhà", subtitle: "Theo dõi cảm biến và thiết bị theo thời gian thực" },
  "/devices": { title: "Thiết bị", subtitle: "Bật/tắt thủ công và quản lý chế độ tự động" },
  "/automations": { title: "Tự động hóa", subtitle: "Các luật điều khiển quạt, đèn và còi báo" },
  "/events": { title: "Cảnh báo & nhật ký", subtitle: "Lịch sử sự kiện của toàn hệ thống" },
};

export function Topbar() {
  const pathname = usePathname();
  const { summary, connected, refresh } = useDashboard();
  const [refreshing, setRefreshing] = useState(false);
  const { logout } = useSession();

  const meta = TITLES[pathname] ?? TITLES["/"];

  const handleRefresh = async () => {
    setRefreshing(true);
    try { await refresh(); }
    finally { setRefreshing(false); }
  };

  return (
    <header className="sticky top-0 z-20 border-b border-white/5 bg-ink-950/80 px-4 py-4 backdrop-blur sm:px-6 lg:px-8">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-white sm:text-xl">{meta.title}</h1>
          <p className="muted mt-0.5">{meta.subtitle}</p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <span
            className={clsx(
              "chip",
              connected ? "bg-brand-500/15 text-brand-400" : "bg-slate-500/15 text-slate-400",
            )}
          >
            {connected ? <Wifi size={14} /> : <WifiOff size={14} />}
            {connected ? "Đã kết nối" : "Mất kết nối"}
          </span>

          <button className="btn-ghost" onClick={handleRefresh} disabled={refreshing}>
            <RefreshCw size={16} className={refreshing ? "animate-spin" : undefined} />
            Làm mới
          </button>

          <Link href="/events" aria-label="Xem cảnh báo" className="relative rounded-xl border border-white/10 p-3 hover:bg-white/5">
            <Bell size={16} />
            {summary && summary.unacknowledged_alerts > 0 && (
              <span className="absolute -right-1 -top-1 grid h-5 min-w-5 place-items-center rounded-full bg-rose-500 px-1 text-[11px] font-bold text-white">
                {summary.unacknowledged_alerts}
              </span>
            )}
          </Link>
          <details className="relative">
            <summary aria-label="Mở cài đặt" className="grid h-11 w-11 cursor-pointer list-none place-items-center rounded-xl border border-white/10 text-slate-300 hover:bg-white/5 [&::-webkit-details-marker]:hidden"><Settings2 size={18} /></summary>
            <div className="absolute right-0 top-full z-40 mt-2 w-[min(21rem,calc(100vw-2rem))] space-y-4 rounded-2xl border border-white/10 bg-ink-900 p-4 shadow-2xl">
              <p className="card-title">Cài đặt & tiện ích</p>
              <QuickActions />
              <button className="btn-ghost w-full" onClick={logout}><LogOut size={16} />Đăng xuất</button>
            </div>
          </details>
        </div>
      </div>
    </header>
  );
}
