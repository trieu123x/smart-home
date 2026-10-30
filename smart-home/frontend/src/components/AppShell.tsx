"use client";

import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { FallAlertBanner } from "./FallAlertBanner";
import { GasAlertBanner } from "./GasAlertBanner";
import { Sidebar } from "./Sidebar";
import { Topbar } from "./Topbar";

/** Dashboard chrome (sidebar, top bar, alert banners); the login page renders bare. */
export function AppShell({ children }: { children: ReactNode }) {
  if (usePathname() === "/login") return <>{children}</>;

  return (
    <div className="flex min-h-screen">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar />
        <FallAlertBanner />
        <GasAlertBanner />
        <main className="flex-1 px-4 pb-10 pt-4 sm:px-6 lg:px-8">{children}</main>
      </div>
    </div>
  );
}
