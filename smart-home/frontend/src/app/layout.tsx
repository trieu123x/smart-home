import type { Metadata } from "next";

import "./globals.css";
import { DashboardProvider } from "@/components/DashboardProvider";
import { FallAlertBanner } from "@/components/FallAlertBanner";
import { Sidebar } from "@/components/Sidebar";
import { Topbar } from "@/components/Topbar";

export const metadata: Metadata = {
  title: "Smart Home | Bảng điều khiển",
  description: "Dashboard giám sát nhà thông minh: phát hiện ngã, quạt và đèn tự động",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="vi">
      <body>
        <DashboardProvider>
          <div className="flex min-h-screen">
            <Sidebar />
            <div className="flex min-w-0 flex-1 flex-col">
              <Topbar />
              <FallAlertBanner />
              <main className="flex-1 px-4 pb-10 pt-4 sm:px-6 lg:px-8">{children}</main>
            </div>
          </div>
        </DashboardProvider>
      </body>
    </html>
  );
}
