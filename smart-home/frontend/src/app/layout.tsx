import type { Metadata } from "next";

import "./globals.css";
import { DashboardProvider } from "@/components/DashboardProvider";
import { FallAlertBanner } from "@/components/FallAlertBanner";
import { GasAlertBanner } from "@/components/GasAlertBanner";
import { Sidebar } from "@/components/Sidebar";
import { Topbar } from "@/components/Topbar";
import { DashboardSession } from "@/components/DashboardSession";

export const metadata: Metadata = {
  title: "Smart Home | Bảng điều khiển",
  description: "Theo dõi ngôi nhà, nhận cảnh báo và điều khiển thiết bị",
  manifest: "/manifest.webmanifest",
  appleWebApp: { capable: true, title: "Smart Home", statusBarStyle: "black-translucent" },
  icons: { icon: "/icons/smart-home-192.png", apple: "/icons/smart-home-192.png" },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="vi">
      <body>
        <DashboardSession><DashboardProvider>
          <div className="flex min-h-screen">
            <Sidebar />
            <div className="flex min-w-0 flex-1 flex-col">
              <Topbar />
              <FallAlertBanner />
              <GasAlertBanner />
              <main id="main-content" className="mx-auto w-full max-w-[1600px] flex-1 px-4 pb-28 pt-6 sm:px-6 lg:px-8 lg:pb-10">{children}</main>
            </div>
          </div>
        </DashboardProvider></DashboardSession>
      </body>
    </html>
  );
}
