"use client";

import { BellRing } from "lucide-react";
import { useEffect, useState } from "react";
import { currentPush, disablePush, enablePush, pushSupported, testPush } from "@/lib/push";

export function PushSettings() {
  const [ready, setReady] = useState(false);
  const [active, setActive] = useState(false);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("");
  const [supported, setSupported] = useState(true);

  useEffect(() => {
    setSupported(pushSupported());
    currentPush().then(sub => setActive(Boolean(sub))).catch(() => undefined).finally(() => setReady(true));
  }, []);

  async function toggle() {
    setBusy(true); setStatus("");
    try {
      if (active) {
        await disablePush(); setActive(false); setStatus("Đã tắt thông báo trên điện thoại này.");
      } else {
        await enablePush(); setActive(true); setStatus("Đã bật thông báo trên điện thoại này.");
      }
    } catch (error) { setStatus(error instanceof Error ? error.message : "Có lỗi xảy ra."); }
    finally { setBusy(false); }
  }

  async function sendTest() {
    setBusy(true); setStatus("");
    try {
      const result = await testPush();
      setStatus(`Yêu cầu gửi đã được chấp nhận: ${result.sent}/${result.total} thiết bị. Kiểm tra thanh thông báo.`);
    } catch (error) { setStatus(error instanceof Error ? error.message : "Có lỗi xảy ra."); }
    finally { setBusy(false); }
  }

  return (
    <section className="rounded-2xl border border-white/10 bg-ink-900 p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="flex items-center gap-2 font-semibold"><BellRing size={18} /> Thông báo trên điện thoại</h2>
          <p className="muted mt-1 max-w-xl text-sm">Nhận cảnh báo ngã, gas/khói và ESP32 mất kết nối ngay cả khi đã đóng website.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button className="btn" type="button" onClick={toggle} disabled={!ready || !supported || busy}>
            {!supported ? "Không hỗ trợ Push" : active ? "Tắt thông báo" : "Bật thông báo"}
          </button>
          {active && <button type="button" className="btn-ghost" onClick={sendTest} disabled={busy}>Gửi thử</button>}
        </div>
      </div>
      {!supported && <p className="mt-2 text-sm text-amber-300">Trên iPhone (iOS 16.4+), hãy thêm website vào màn hình chính rồi mở từ biểu tượng đó trước khi bật thông báo. Website phải chạy HTTPS.</p>}
      {status && <p role="status" className="mt-2 text-sm text-slate-300">{status}</p>}
    </section>
  );
}
