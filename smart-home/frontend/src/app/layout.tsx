import type { Metadata } from "next";

import "./globals.css";
import { AppShell } from "@/components/AppShell";
import { DashboardProvider } from "@/components/DashboardProvider";

export const metadata: Metadata = {
  title: "Smart Home | Bảng điều khiển",
  description: "Dashboard giám sát nhà thông minh: phát hiện ngã, quạt và đèn tự động",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="vi">
      <body>
        <DashboardProvider>
          <AppShell>{children}</AppShell>
        </DashboardProvider>
      </body>
    </html>
  );
}
