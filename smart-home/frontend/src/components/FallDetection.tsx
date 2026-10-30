"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { ArrowLeftRight, Play, Settings2, ShieldCheck, Square, Video, Wifi } from "lucide-react";
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
  const [viewError, setViewError] = useState("");
  const [frameError, setFrameError] = useState<Partial<Record<Source, string>>>({});
  const [busy, setBusy] = useState(false);
  const [selectedSource, setSelectedSource] = useState<Source | null>(null);
  const selectedRef = useRef<Source>("adb");
  const [droidHost, setDroidHost] = useState("");
  const [droidPort, setDroidPort] = useState("4747");
  const viewRef = useRef<FallView | null>(null);

  useEffect(() => {
    selectedRef.current = selectedSource ?? data?.camera.analysis_source ?? "adb";
  }, [selectedSource, data?.camera.analysis_source]);

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
        setViewError("");
        for (const source of SOURCES) {
          if (next.camera.cameras?.[source]?.state !== "connected") clear(source);
        }
      } catch (err) {
        if (!abort.signal.aborted) {
          viewRef.current = null;
          setData(null);
          setViewError(err instanceof Error ? err.message : "Không nhận được hình ảnh camera. Vui lòng kiểm tra kết nối.");
        }
      } finally {
        if (!abort.signal.aborted) viewTimer = setTimeout(pollView, 600);
      }
    };
    const pollFrame = async (source: Source) => {
      try {
        if (selectedRef.current === source && viewRef.current?.camera.cameras?.[source]?.state === "connected") {
          const response = await fetch(`${API_URL}/api/fall/frame?source=${source}&seq=${sequences[source]}`, {
            signal: abort.signal, credentials: "include", cache: "no-store",
          });
          if (!response.ok) throw new Error("Hình ảnh camera đang bị gián đoạn.");
          setFrameError(prev => prev[source] ? { ...prev, [source]: "" } : prev);
          if (response.status === 200) {
            const blob = await response.blob();
            if (abort.signal.aborted || selectedRef.current !== source || viewRef.current?.camera.cameras?.[source]?.state !== "connected") return;
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
          setFrameError(prev => ({ ...prev, [source]: err instanceof Error ? err.message : "Hình ảnh camera bị gián đoạn. Vui lòng kiểm tra kết nối." }));
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
      if (!Number.isInteger(port) || port < 1024 || port > 65535) throw new Error("Cổng kết nối phải từ 1024 đến 65535.");
      await api.connectDroidCam(droidHost.trim(), port);
      await api.selectFallSource("droidcam");
      setSelectedSource("droidcam");
      const next = await api.fallView<FallView>();
      viewRef.current = next;
      setData(next);
    } catch (err) { setError(err instanceof Error ? err.message : "Không kết nối được camera Wi-Fi. Hãy kiểm tra điện thoại và mạng Wi-Fi."); }
    finally { setBusy(false); }
  }

  async function selectSource(source: Source) {
    setError("");
    if (!data?.camera.cameras?.[source]?.configured) {
      setSelectedSource(source);
      return;
    }
    setBusy(true); setError("");
    try {
      await api.selectFallSource(source);
      setSelectedSource(source);
      const next = await api.fallView<FallView>();
      viewRef.current = next;
      setData(next);
    } catch (err) { setError(err instanceof Error ? err.message : "Chưa thể chọn camera này. Vui lòng thử lại."); }
    finally { setBusy(false); }
  }

  const state = data?.camera;
  const source = selectedSource ?? state?.analysis_source ?? "adb";
  const current = state?.cameras?.[source];
  const analyzed = state?.analysis_enabled && current?.state === "connected" && state.analysis_source === source ? data?.view : null;
  const tracks = analyzed?.tracks ?? [];
  const danger = tracks.some(track => track.danger);
  const image = current?.state === "connected" ? (analyzed ? `data:image/jpeg;base64,${analyzed.image}` : raw[source]) : null;
  const watching = state?.analysis_enabled && state.analysis_source === source;

  return (
    <section className="card space-y-5" aria-labelledby="camera-title" aria-busy={busy}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 id="camera-title" className="card-title flex items-center gap-2"><Video size={19} className="text-brand-400" /> Camera trực tiếp</h2>
          <p className="muted mt-1">Quan sát ngôi nhà và theo dõi té ngã</p>
        </div>
        <span className={`chip ${danger ? "bg-rose-500/15 text-rose-300" : current?.state === "connected" ? "bg-brand-500/15 text-brand-400" : "bg-white/5 text-slate-400"}`} role="status">
          <span className={`h-2 w-2 rounded-full ${danger ? "bg-rose-400" : current?.state === "connected" ? "bg-brand-400" : "bg-slate-500"}`} />
          {danger ? "Cảnh báo té ngã" : STATES[current?.state || ""] || "Đang tải camera"}
        </span>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="inline-flex rounded-xl border border-white/10 bg-ink-950/50 p-1" role="group" aria-label="Chuyển camera">
          {SOURCES.map(option => (
            <button key={option} type="button" aria-pressed={source === option} disabled={busy || !state}
              onClick={() => void selectSource(option)}
              className={`inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-sm font-medium transition disabled:opacity-50 ${source === option ? "bg-brand-500 text-ink-950 shadow-sm" : "text-slate-400 hover:bg-white/5 hover:text-white"}`}>
              {option === "adb" ? <Video size={16} /> : <Wifi size={16} />}
              {option === "adb" ? "USB" : "Wi-Fi"}
            </button>
          ))}
        </div>
        <span className="flex items-center gap-1.5 text-xs text-slate-400"><ArrowLeftRight size={14} /> Chọn kết nối để chuyển camera</span>
      </div>

      <div className="relative aspect-video overflow-hidden rounded-2xl border border-white/10 bg-ink-950">
        {image ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={image} alt={source === "adb" ? "Hình ảnh trực tiếp từ camera USB" : "Hình ảnh trực tiếp từ camera Wi-Fi"} className="h-full w-full object-contain" />
        ) : (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 p-5 text-center">
            <span className="grid h-14 w-14 place-items-center rounded-2xl bg-white/5 text-slate-400"><Video size={26} /></span>
            <p className="text-sm font-medium text-slate-200">{!state ? "Đang kết nối hệ thống camera" : current?.state === "connected" ? "Đang tải hình ảnh" : current?.enabled ? "Đang kết nối camera" : "Camera chưa bật"}</p>
            <p className="max-w-sm text-xs leading-5 text-slate-400">{source === "droidcam" && !current?.configured ? "Mở DroidCam trên điện thoại, sau đó nhập địa chỉ Wi-Fi trong phần Thiết lập kết nối bên dưới." : source === "adb" ? "Kết nối điện thoại bằng cáp USB và nhấn Bật camera để bắt đầu." : "Nhấn Bật camera để xem hình ảnh từ điện thoại."}</p>
          </div>
        )}
        {analyzed && (
          <svg className="pointer-events-none absolute inset-0 h-full w-full" viewBox={`0 0 ${analyzed.width} ${analyzed.height}`} preserveAspectRatio="xMidYMid meet" aria-label="Kết quả nhận diện">
            {tracks.map(track => {
              const [x1, y1, x2, y2] = track.box;
              const color = track.danger ? "#fb7185" : track.pending ? "#fbbf24" : "#34d399";
              const label = track.danger ? `NGÃ #${track.id}` : track.pending ? `Xác nhận ${track.streak}/${state?.confirmations}` : `Người #${track.id}`;
              return <g key={track.id}>
                <rect x={x1 * analyzed.width} y={y1 * analyzed.height} width={(x2 - x1) * analyzed.width} height={(y2 - y1) * analyzed.height} fill="none" stroke={color} strokeWidth="3" />
                <text x={x1 * analyzed.width + 4} y={Math.max(18, y1 * analyzed.height - 7)} fill={color} stroke="#020617" strokeWidth="3" paintOrder="stroke" fontSize="15" fontWeight="bold">{label}</text>
              </g>;
            })}
          </svg>
        )}
      </div>

      <div className="flex flex-wrap items-center justify-between gap-4">
        <button className={current?.enabled ? "btn-ghost" : "btn-primary"} type="button"
          disabled={busy || !current?.configured}
          onClick={() => void action(current?.enabled ? "stop" : "start", undefined, source)}>
          {current?.enabled ? <Square size={16} /> : <Play size={16} />}
          {busy ? "Đang xử lý..." : current?.enabled ? "Tắt camera" : "Bật camera"}
        </button>
        <div className="flex items-center gap-3">
          <div>
            <p id="fall-toggle-label" className="text-sm font-medium text-slate-200">Phát hiện té ngã</p>
            <p className="muted mt-1">{watching ? "Đang bật" : "Đang tắt"}{watching && current?.state === "connected" ? ` · ${tracks.length} người trong khung hình` : ""}</p>
          </div>
          <button type="button" role="switch" aria-checked={!!watching} aria-labelledby="fall-toggle-label"
            disabled={busy || !state?.ready || !current?.enabled || current.state !== "connected" || state.analysis_source !== source}
            onClick={() => void action("analysis", !watching)}
            className={`relative inline-flex h-7 w-12 shrink-0 items-center rounded-full transition disabled:cursor-not-allowed disabled:opacity-40 ${watching ? "bg-brand-500" : "bg-slate-600"}`}>
            <span className={`inline-block h-5 w-5 rounded-full bg-white shadow transition-transform ${watching ? "translate-x-6" : "translate-x-1"}`} />
          </button>
        </div>
      </div>

      {source === "droidcam" && (
        <details className="rounded-xl border border-white/10 bg-ink-950/30 p-4" open={!current?.configured || undefined}>
          <summary className="cursor-pointer text-sm font-medium text-slate-300"><Settings2 size={15} className="mr-2 inline" />Thiết lập kết nối Wi-Fi</summary>
          <p className="muted mt-3">Điện thoại và máy chủ cần dùng chung mạng Wi-Fi. Nhập IP và cổng hiển thị trong DroidCam.</p>
          <form onSubmit={connectDroidCam} className="mt-3 grid items-end gap-3 sm:grid-cols-[minmax(0,1fr)_6rem_auto]">
            <label className="block text-xs text-slate-400">Địa chỉ IP
              <input className="input mt-1.5" value={droidHost} onChange={e => setDroidHost(e.target.value)} placeholder="192.168.1.20" autoComplete="off" required disabled={busy} />
            </label>
            <label className="block text-xs text-slate-400">Cổng
              <input className="input mt-1.5" type="number" min={1024} max={65535} value={droidPort} onChange={e => setDroidPort(e.target.value)} required disabled={busy} />
            </label>
            <button className="btn-primary" type="submit" disabled={busy}>{busy ? "Đang kết nối..." : "Kết nối"}</button>
          </form>
        </details>
      )}
      {(error || viewError || frameError[source] || state?.error) && <p role="alert" className="rounded-xl bg-rose-500/10 p-3 text-sm text-rose-300">{error || viewError || frameError[source] || "Camera hiện chưa sẵn sàng. Hãy kiểm tra kết nối và thử lại."}</p>}
      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-white/5 pt-4 text-xs text-slate-400">
        <span className="flex items-center gap-1.5"><ShieldCheck size={14} /> {state?.ready ? "Nhận diện đã sẵn sàng" : "Nhận diện chưa sẵn sàng"}</span>
        <span>Thông báo khẩn cấp: {TELEGRAM[state?.telegram ?? ""] ?? "Đang cập nhật"}</span>
      </div>
    </section>
  );
}
