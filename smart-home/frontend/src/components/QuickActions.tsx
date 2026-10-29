"use client";

import { Bell, BellOff, Download, Info, Settings2, Smartphone, X } from "lucide-react";
import { createPortal } from "react-dom";
import { useEffect, useRef, useState } from "react";
import { currentPush, disablePush, enablePush, pushSupported } from "@/lib/push";

type InstallEvent = Event & {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
};

function isiOSDevice() {
  if (typeof navigator === "undefined") return false;
  return /iPad|iPhone|iPod/.test(navigator.userAgent) ||
    (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
}

function isMobileDevice() {
  if (typeof navigator === "undefined") return false;
  return /Android|iPhone|iPad|iPod|Mobile/i.test(navigator.userAgent) || isiOSDevice();
}

function isStandalone() {
  if (typeof window === "undefined") return false;
  return window.matchMedia("(display-mode: standalone)").matches ||
    Boolean((navigator as Navigator & { standalone?: boolean }).standalone);
}

export function QuickActions() {
  const [pushActive, setPushActive] = useState(false);
  const [pushBusy, setPushBusy] = useState(false);
  const [pushSupportedHere, setPushSupportedHere] = useState(true);
  const [pushPermission, setPushPermission] = useState<NotificationPermission | "unsupported">("default");
  const [pushOpen, setPushOpen] = useState(false);
  const [pushMessage, setPushMessage] = useState("");
  const [installPrompt, setInstallPrompt] = useState<InstallEvent | null>(null);
  const [installed, setInstalled] = useState(false);
  const [ios, setIos] = useState(false);
  const [setupOpen, setSetupOpen] = useState(false);
  const [installGuide, setInstallGuide] = useState(false);
  const setupCloseRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    let mounted = true;
    const mobile = isMobileDevice();
    const standalone = isStandalone();
    const supported = pushSupported();

    setPushSupportedHere(supported);
    setPushPermission(supported ? Notification.permission : "unsupported");
    setInstalled(standalone);
    setIos(isiOSDevice());

    // Auto-open only on mobile and only once per page load. A dismissed
    // reminder can appear again on the next visit, never on every route change.
    void currentPush().then(subscription => {
      if (!mounted) return;
      const active = Boolean(subscription) && supported && Notification.permission === "granted";
      setPushActive(active);
      if (mobile && (!active || !standalone)) setSetupOpen(true);
    }).catch(() => {
      if (mounted && mobile) setSetupOpen(true);
    });

    const onPrompt = (event: Event) => {
      event.preventDefault();
      setInstallPrompt(event as InstallEvent);
    };
    const onInstalled = () => {
      setInstalled(true);
      setInstallPrompt(null);
      setInstallGuide(false);
    };
    const onVisible = () => {
      if (document.visibilityState !== "visible") return;
      setInstalled(isStandalone());
      const supportedNow = pushSupported();
      setPushSupportedHere(supportedNow);
      if (supportedNow) {
        setPushPermission(Notification.permission);
        void currentPush().then(subscription => {
          if (mounted) setPushActive(Boolean(subscription) && Notification.permission === "granted");
        }).catch(() => undefined);
      }
    };

    window.addEventListener("beforeinstallprompt", onPrompt);
    window.addEventListener("appinstalled", onInstalled);
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      mounted = false;
      window.removeEventListener("beforeinstallprompt", onPrompt);
      window.removeEventListener("appinstalled", onInstalled);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, []);

  // The modal closes automatically once both tasks have been completed.
  useEffect(() => {
    if (setupOpen && installed && pushActive) setSetupOpen(false);
  }, [installed, pushActive, setupOpen]);

  useEffect(() => {
    if (!setupOpen) return;
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    setupCloseRef.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setSetupOpen(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = previousOverflow;
      previousFocus?.focus();
    };
  }, [setupOpen]);

  async function togglePush() {
    if (pushBusy) return;
    setPushMessage("");
    if (!pushActive && ios && !installed) {
      setSetupOpen(true);
      setInstallGuide(true);
      return;
    }
    if (!pushActive && pushPermission === "denied") {
      setPushMessage("Bạn đã chặn thông báo. Hãy mở cài đặt quyền của website trên điện thoại, cho phép thông báo rồi tải lại trang.");
      setSetupOpen(true);
      return;
    }
    setPushBusy(true);
    try {
      if (pushActive) {
        await disablePush();
        setPushActive(false);
        setPushMessage("Đã tắt thông báo trên thiết bị này.");
      } else {
        await enablePush();
        setPushActive(true);
        setPushPermission("granted");
        setPushMessage("Đã bật thông báo trên điện thoại này.");
      }
    } catch (error) {
      setPushPermission(pushSupported() ? Notification.permission : "unsupported");
      setPushMessage(error instanceof Error ? error.message : "Không thể thay đổi cài đặt thông báo.");
    } finally {
      setPushBusy(false);
    }
  }

  async function install() {
    if (installed) return;
    if (!installPrompt) {
      setInstallGuide(true);
      setSetupOpen(true);
      return;
    }
    try {
      await installPrompt.prompt();
      const choice = await installPrompt.userChoice;
      setInstallPrompt(null);
      if (choice.outcome !== "accepted") setInstallGuide(true);
    } catch {
      setInstallPrompt(null);
      setInstallGuide(true);
      setSetupOpen(true);
    }
  }

  const installSteps = ios
    ? "Mở Smart Home bằng Safari → nhấn Chia sẻ → Thêm vào Màn hình chính → mở Smart Home từ biểu tượng vừa thêm. Sau đó chọn Bật thông báo."
    : /Android/i.test(typeof navigator === "undefined" ? "" : navigator.userAgent)
      ? "Mở bằng Chrome → menu ⋮ → Cài đặt ứng dụng / Thêm vào màn hình chính → mở từ biểu tượng trên điện thoại."
      : "Mở menu trình duyệt Chrome hoặc Edge và chọn Cài đặt ứng dụng (nếu có).";

  return (
    <>
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative">
          <button type="button" aria-label="Cài đặt thông báo" aria-expanded={pushOpen}
            className={`btn-ghost whitespace-nowrap ${pushActive ? "border-brand-500/40 text-brand-400" : ""}`}
            onClick={() => { setPushOpen(!pushOpen); }}>
            {pushActive ? <Bell size={16} /> : <BellOff size={16} />}
            <span className="hidden sm:inline">{pushActive ? "Thông báo: Bật" : "Bật thông báo"}</span>
            <span className="sm:hidden">Thông báo</span>
          </button>
          {pushOpen && (
            <div className="absolute right-0 top-full z-40 mt-2 w-[min(20rem,calc(100vw-2rem))] rounded-xl border border-white/15 bg-ink-900 p-4 shadow-2xl">
              <div className="flex items-center justify-between gap-2"><strong className="text-sm">Thông báo trên điện thoại</strong>
                <button type="button" aria-label="Đóng" onClick={() => setPushOpen(false)}><X size={16} /></button></div>
              <p className="mt-2 text-xs text-slate-400">Nhận cảnh báo té ngã, gas/khói và mất kết nối ngay cả khi không mở Smart Home.</p>
              <button type="button" className="btn-primary mt-3 w-full" disabled={pushBusy || (!pushActive && !pushSupportedHere)}
                onClick={() => void togglePush()}>{pushBusy ? "Đang xử lý..." : pushActive ? "Tắt thông báo" : "Bật thông báo"}</button>
              {!pushSupportedHere && <p className="mt-2 text-xs text-amber-300">Trên iPhone, hãy thêm Smart Home vào màn hình chính và mở từ biểu tượng đó để bật thông báo.</p>}
              {pushMessage && <p role="status" className="mt-2 text-xs text-slate-200">{pushMessage}</p>}
            </div>
          )}
        </div>
        <div className="relative">
          <button type="button" className="btn-ghost whitespace-nowrap" onClick={() => { void install(); setPushOpen(false); }}
            title={installed ? "Đang chạy ở chế độ ứng dụng" : "Thêm website ra màn hình chính"}>
            {installed ? <Smartphone size={16} /> : <Download size={16} />}
            <span className="hidden sm:inline">{installed ? "Đã cài ứng dụng" : "Cài ứng dụng"}</span>
            <span className="sm:hidden">Cài ứng dụng</span>
          </button>
        </div>
      </div>

      {setupOpen && typeof document !== "undefined" && createPortal(
        <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/75 px-4 py-6 backdrop-blur-sm"
          role="presentation" onMouseDown={event => { if (event.target === event.currentTarget) setSetupOpen(false); }}>
          <section role="dialog" aria-modal="true" aria-labelledby="smart-home-setup-title"
            aria-describedby="smart-home-setup-description"
            className="w-full max-w-md max-h-[calc(100dvh-2rem)] overflow-y-auto rounded-2xl border border-white/15 bg-ink-900 p-5 shadow-2xl sm:p-6"
            onKeyDown={event => {
              if (event.key !== "Tab") return;
              const focusable = Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>("button:not(:disabled)"));
              const first = focusable[0];
              const last = focusable[focusable.length - 1];
              if (!first || !last) return;
              if (event.shiftKey && document.activeElement === first) {
                event.preventDefault(); last.focus();
              } else if (!event.shiftKey && document.activeElement === last) {
                event.preventDefault(); first.focus();
              }
            }}>
            <div className="flex items-start justify-between gap-4">
              <div>
                <div className="flex items-center gap-2 text-brand-400"><Settings2 size={18} /><span className="text-xs font-semibold uppercase tracking-wider">Thiết lập Smart Home</span></div>
                <h2 id="smart-home-setup-title" className="mt-2 text-xl font-semibold text-white">Đừng bỏ lỡ cảnh báo quan trọng</h2>
                <p id="smart-home-setup-description" className="mt-2 text-sm text-slate-300">
                  Hoàn tất các bước còn thiếu để nhận cảnh báo ngã, gas/khói và truy cập nhanh trên điện thoại.
                </p>
              </div>
              <button ref={setupCloseRef} type="button" aria-label="Đóng hướng dẫn thiết lập"
                onClick={() => setSetupOpen(false)} className="rounded-lg p-1.5 text-slate-400 hover:bg-white/10 hover:text-white">
                <X size={20} />
              </button>
            </div>

            <div className="mt-5 space-y-3">
              {!installed && (
                <div className="rounded-xl border border-white/10 bg-ink-950/65 p-4">
                  <div className="flex items-center gap-2 font-semibold text-white"><Smartphone size={18} className="text-brand-400" /> Thêm ra màn hình chính</div>
                  <p className="mt-2 text-sm text-slate-400">Mở Smart Home như ứng dụng mà không cần vào trình duyệt.</p>
                  <button type="button" className="btn-primary mt-3 w-full" onClick={() => void install()}>
                    <Download size={16} /> {installPrompt ? "Cài ứng dụng ngay" : "Xem cách thêm vào màn hình chính"}
                  </button>
                  {installGuide && <p className="mt-3 rounded-lg bg-white/5 p-3 text-sm leading-6 text-slate-200">{installSteps}</p>}
                </div>
              )}

              {!pushActive && (
                <div className="rounded-xl border border-white/10 bg-ink-950/65 p-4">
                  <div className="flex items-center gap-2 font-semibold text-white"><Bell size={18} className="text-brand-400" /> Bật thông báo cảnh báo</div>
                  <p className="mt-2 text-sm text-slate-400">Nhận cảnh báo trên điện thoại ngay cả khi không mở Smart Home.</p>
                  {ios && !installed ? (
                    <p className="mt-3 rounded-lg bg-amber-500/10 p-3 text-sm text-amber-200">Trên iPhone, hãy thêm Smart Home vào màn hình chính rồi mở từ biểu tượng để bật thông báo.</p>
                  ) : !pushSupportedHere ? (
                    <p className="mt-3 rounded-lg bg-amber-500/10 p-3 text-sm text-amber-200">Thiết bị chưa thể nhận thông báo. Hãy mở Smart Home bằng đường dẫn an toàn hoặc thử trình duyệt khác.</p>
                  ) : pushPermission === "denied" ? (
                    <p className="mt-3 rounded-lg bg-amber-500/10 p-3 text-sm text-amber-200">Quyền đã bị chặn. Vào Cài đặt trang web / Thông báo trên điện thoại, cấp lại quyền rồi tải lại trang.</p>
                  ) : (
                    <button type="button" className="btn-primary mt-3 w-full" disabled={pushBusy} onClick={() => void togglePush()}>
                      <Bell size={16} /> {pushBusy ? "Đang bật..." : "Bật thông báo ngay"}
                    </button>
                  )}
                </div>
              )}
            </div>

            {pushMessage && <p role="status" className="mt-3 text-sm text-amber-200">{pushMessage}</p>}
            <p className="mt-4 flex items-start gap-2 text-xs text-slate-500"><Info size={14} className="mt-0.5 shrink-0" /> Chỉ yêu cầu quyền thông báo khi bạn nhấn Bật. Bạn có thể chọn Để sau; lời nhắc sẽ xuất hiện lại trong lần mở website tiếp theo nếu chưa hoàn tất.</p>
            <button type="button" className="btn-ghost mt-4 w-full" onClick={() => setSetupOpen(false)}>Để sau</button>
          </section>
        </div>, document.body,
      )}
    </>
  );
}
