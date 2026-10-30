"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { Check, Play, Radio, Square, Video, Wifi } from "lucide-react";
import { API_URL, api } from "@/lib/api";

type Source = "adb" | "droidcam";
interface Track {
  id: number;
  box: [number, number, number, number];
  fall_score: number | null;
  danger: boolean;
  pending: boolean;
  streak: number;
  state: string;
  window_frames: number;
  window_target: number;
}
interface CameraStatus {
  name: string;
  configured: boolean;
  enabled: boolean;
  state: string;
  sequence: number;
  epoch: number;
  threshold: number;
  confirmations: number;
}
interface Camera extends CameraStatus {
  ready: boolean;
  analysis_enabled: boolean;
  analysis_source: Source;
  cameras: Record<Source, CameraStatus>;
  error: string | null;
  telegram: string;
  telegram_detail: string;
  ai_device: string | null;
  gpu_name: string | null;
}
interface FallView {
  camera: Camera;
  view: { image: string; width: number; height: number; tracks: Track[]; age: number } | null;
}
const SOURCES: Source[] = ["adb", "droidcam"];
const STATES: Record<string, string> = {
  stopped: "Đã tắt", connecting: "Đang kết nối", connected: "Trực tiếp",
  reconnecting: "Đang kết nối lại", unavailable: "Chưa sẵn sàng",
};
const TELEGRAM: Record<string, string> = {
  configured: "Sẵn sàng", not_configured: "Chưa sẵn sàng", sending: "Đang gửi",
  sent: "Đã gửi", retrying: "Đang thử lại", error: "Chưa gửi được", cooldown: "Tạm dừng gửi",
};

export function FallDetection() {
  const [data, setData] = useState<FallView | null>(null);
  const [raw, setRaw] = useState<Record<Source, string | null>>({ adb: null, droidcam: null });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [droidHost, setDroidHost] = useState("");
  const [droidPort, setDroidPort] = useState("4747");
  const viewRef = useRef<FallView | null>(null);

  useEffect(() => {
    const abort = new AbortController();
    let viewTimer: ReturnType<typeof setTimeout>;
    const frameTimers: Partial<Record<Source, ReturnType<typeof setTimeout>>> = {};
    const objectUrls: Partial<Record<Source, string>> = {};
    const sequences: Record<Source, number> = { adb: -1, droidcam: -1 };
    const clear = (source: Source) => {
      if (objectUrls[source]) URL.revokeObjectURL(objectUrls[source]!);
      delete objectUrls[source];
      sequences[source] = -1;
      setRaw(prev => prev[source] ? { ...prev, [source]: null } : prev);
    };
    const pollView = async () => {
      try {
        const next = await api.fallView<FallView>(abort.signal);
        if (abort.signal.aborted) return;
        viewRef.current = next;
        setData(next);
        setError("");
        for (const source of SOURCES) {
          if (next.camera.cameras?.[source]?.state !== "connected") clear(source);
        }
      } catch (err) {
        if (!abort.signal.aborted) {
          viewRef.current = null;
          setData(null);
          setError(err instanceof Error ? err.message : "Không nhận được hình ảnh camera. Vui lòng kiểm tra kết nối.");
        }
      } finally {
        if (!abort.signal.aborted) viewTimer = setTimeout(pollView, 600);
      }
    };
    const pollFrame = async (source: Source) => {
      try {
        if (viewRef.current?.camera.cameras?.[source]?.state === "connected") {
          const response = await fetch(`${API_URL}/api/fall/frame?source=${source}&seq=${sequences[source]}`, {
            signal: abort.signal, credentials: "include", cache: "no-store",
          });
          if (!response.ok) throw new Error("Hình ảnh camera đang bị gián đoạn.");
          if (response.status === 200) {
            const blob = await response.blob();
            if (abort.signal.aborted || viewRef.current?.camera.cameras?.[source]?.state !== "connected") return;
            const next = URL.createObjectURL(blob);
            const previous = objectUrls[source];
            objectUrls[source] = next;
            setRaw(prev => ({ ...prev, [source]: next }));
            if (previous) URL.revokeObjectURL(previous);
            sequences[source] = Number(response.headers.get("X-Frame-Sequence") ?? -1);
          }
        }
      } catch (err) {
        if (!abort.signal.aborted) {
          clear(source);
          setError(err instanceof Error ? err.message : "Hình ảnh camera bị gián đoạn. Vui lòng kiểm tra kết nối.");
        }
      } finally {
        if (!abort.signal.aborted) frameTimers[source] = setTimeout(() => void pollFrame(source), 400);
      }
    };
    void pollView();
    for (const source of SOURCES) void pollFrame(source);
    return () => {
      abort.abort();
      clearTimeout(viewTimer);
      for (const source of SOURCES) {
        clearTimeout(frameTimers[source]);
        if (objectUrls[source]) URL.revokeObjectURL(objectUrls[source]!);
      }
    };
  }, []);

  async function action(command: "start" | "stop" | "analysis", enabled?: boolean, source?: Source) {
    setBusy(true); setError("");
    try {
      await api.fallAction(command, enabled, source);
      const next = await api.fallView<FallView>();
      viewRef.current = next;
      setData(next);
    } catch (err) { setError(err instanceof Error ? err.message : "Thao tác chưa thành công."); }
    finally { setBusy(false); }
  }

  async function connectDroidCam(event: FormEvent) {
    event.preventDefault();
    setBusy(true); setError("");
    try {
      const port = Number(droidPort);
      if (!Number.isInteger(port)) throw new Error("Cổng kết nối không hợp lệ.");
      await api.connectDroidCam(droidHost.trim(), port);
      const next = await api.fallView<FallView>();
      viewRef.current = next;
      setData(next);
    } catch (err) { setError(err instanceof Error ? err.message : "Không kết nối được camera Wi-Fi. Hãy kiểm tra điện thoại và mạng Wi-Fi."); }
    finally { setBusy(false); }
  }

  async function selectSource(source: Source) {
    setBusy(true); setError("");
    try {
      await api.selectFallSource(source);
      const next = await api.fallView<FallView>();
      viewRef.current = next;
      setData(next);
    } catch (err) { setError(err instanceof Error ? err.message : "Chưa thể chọn camera này. Vui lòng thử lại."); }
    finally { setBusy(false); }
  }

  const state = data?.camera;
  const analyzed = state?.analysis_enabled && state.state === "connected" ? data?.view : null;
  const tracks = analyzed?.tracks ?? [];
  const danger = tracks.some(track => track.danger);

  return (
    <section className="card space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="card-title">Camera & phát hiện ngã</h2>
        <span className={`chip ${danger ? "bg-rose-500/15 text-rose-300" : "bg-brand-500/15 text-brand-400"}`}>
          {danger ? "CẢNH BÁO TÉ NGÃ" : state?.ready ? "Sẵn sàng theo dõi" : "Đang khởi động"}
        </span>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        {SOURCES.map(source => {
          const current = state?.cameras?.[source];
          const chosen = state?.analysis_source === source;
          const overlay = chosen ? analyzed : null;
          const image = overlay ? `data:image/jpeg;base64,${overlay.image}` : raw[source];
          return (
            <div key={source} className={`min-w-0 rounded-xl border p-3 ${chosen ? "border-brand-500/40 bg-brand-500/5" : "border-white/10 bg-ink-950/40"}`}>
              <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                <h3 className="flex items-center gap-2 text-sm font-semibold">{source === "adb" ? <Video size={16} /> : <Wifi size={16} />}
                  {source === "adb" ? "Camera qua cáp USB" : "Camera Wi-Fi (DroidCam)"}
                </h3>
                <span className="text-xs text-slate-400">{STATES[current?.state || ""] || "Đang tải"}</span>
              </div>
              <div className="relative aspect-video overflow-hidden rounded-lg bg-ink-950">
                {image ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={image} alt={`Camera ${source}`} className="h-full w-full object-contain" />
                ) : (
                  <div className="absolute inset-0 grid place-items-center p-3 text-center text-xs text-slate-400">
                    <div><Video className="mx-auto mb-2" size={26} />
                      {source === "droidcam" && !current?.configured ? "Nhập địa chỉ camera trên điện thoại" : STATES[current?.state || ""] || "Chờ camera"}</div>
                  </div>
                )}
                {overlay && (
                  <svg className="pointer-events-none absolute inset-0 h-full w-full" viewBox={`0 0 ${overlay.width} ${overlay.height}`} preserveAspectRatio="xMidYMid meet" aria-label="Kết quả nhận diện">
                    {tracks.map(track => {
                      const [x1, y1, x2, y2] = track.box;
                      const color = track.danger ? "#fb7185" : track.pending ? "#fbbf24" : "#34d399";
                      const label = track.danger ? `NGÃ #${track.id}` : track.pending ? `Xác nhận ${track.streak}/${state?.confirmations}` : `Người #${track.id}`;
                      return <g key={track.id}>
                        <rect x={x1 * overlay.width} y={y1 * overlay.height} width={(x2 - x1) * overlay.width} height={(y2 - y1) * overlay.height} fill="none" stroke={color} strokeWidth="3" />
                        <text x={x1 * overlay.width + 4} y={Math.max(18, y1 * overlay.height - 7)} fill={color} stroke="#020617" strokeWidth="3" paintOrder="stroke" fontSize="15" fontWeight="bold">{label}</text>
                      </g>;
                    })}
                  </svg>
                )}
              </div>
              {source === "droidcam" && (
                <form onSubmit={connectDroidCam} className="mt-3 flex flex-wrap items-center gap-2">
                  <input className="input min-w-0 flex-[2] text-xs" value={droidHost} onChange={e => setDroidHost(e.target.value)}
                    placeholder="Địa chỉ camera (ví dụ 192.168.1.20)" aria-label="Địa chỉ IP camera" required />
                  <input className="input w-20 text-xs" type="number" min={1024} max={65535} value={droidPort}
                    onChange={e => setDroidPort(e.target.value)} aria-label="Cổng kết nối camera" required />
                  <button className="btn-primary text-xs" type="submit" disabled={busy}>Kết nối</button>
                </form>
              )}
              <div className="mt-3 flex flex-wrap gap-2">
                <button className="btn-ghost text-xs" type="button" disabled={busy || !current?.configured || current.enabled}
                  onClick={() => void action("start", undefined, source)}><Play size={14} /> Bật</button>
                <button className="btn-ghost text-xs" type="button" disabled={busy || !current?.enabled}
                  onClick={() => void action("stop", undefined, source)}><Square size={14} /> Tắt</button>
                <button className={`btn text-xs ${chosen ? "bg-brand-500/15 text-brand-400" : "border border-white/10 text-slate-300 hover:bg-white/5"}`}
                  type="button" disabled={busy || !current?.configured} onClick={() => void selectSource(source)}>
                  {chosen ? <Check size={14} /> : <Radio size={14} />}{chosen ? "Đang theo dõi" : "Dùng để theo dõi"}
                </button>
              </div>
            </div>
          );
        })}
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-white/5 pt-3">
        <div className="text-xs text-slate-400">
          <p>Camera đang theo dõi: <b className="text-slate-200">{state?.analysis_source === "droidcam" ? "Camera Wi-Fi" : "Camera USB"}</b></p>
          <p className="mt-1">{state?.ready ? "Hệ thống nhận diện đã sẵn sàng" : "Đang chuẩn bị nhận diện"}</p>
          <p className="mt-1">{tracks.length} người đang được theo dõi</p>
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={state?.analysis_enabled ?? false}
            disabled={busy || !state?.ready || !state.enabled || state.state !== "connected"}
            onChange={event => void action("analysis", event.target.checked)} />
          Theo dõi té ngã
        </label>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-white/5 pt-3">
        <p className="text-xs text-slate-400">Thông báo khẩn cấp: {TELEGRAM[state?.telegram ?? ""] ?? "Đang cập nhật"}</p>
      </div>
      {(error || state?.error) && <p role="alert" className="text-sm text-rose-300">{error || "Camera hiện chưa sẵn sàng. Hãy kiểm tra kết nối và thử lại."}</p>}
      <p className="text-xs text-slate-500">Bạn có thể xem cả hai camera và chọn một camera để nhận diện té ngã. Camera Wi-Fi cần dùng chung mạng với hệ thống.</p>
    </section>
  );
}
