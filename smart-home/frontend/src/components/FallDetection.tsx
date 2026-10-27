"use client";

import { useEffect, useRef, useState } from "react";
import { Play, Square, Video } from "lucide-react";
import { API_URL, api } from "@/lib/api";

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
interface Camera {
  name: string; configured: boolean; enabled: boolean; state: string;
  ready: boolean; analysis_enabled: boolean; threshold: number; confirmations: number;
  error: string | null; telegram: string; telegram_detail: string;
  ai_device: string | null; gpu_name: string | null;
}
interface FallView {
  camera: Camera;
  view: { image: string; width: number; height: number; tracks: Track[]; age: number } | null;
}

const STATES: Record<string, string> = {
  stopped: "Camera đã tắt", connecting: "Đang kết nối camera", connected: "Camera trực tiếp",
  reconnecting: "Mất hình · đang kết nối lại", unavailable: "Camera chưa sẵn sàng",
};
const TELEGRAM: Record<string, string> = {
  configured: "Sẵn sàng", not_configured: "Chưa cấu hình", sending: "Đang gửi",
  sent: "Đã gửi", retrying: "Đang thử lại", error: "Lỗi gửi", cooldown: "Chống gửi lặp",
};

export function FallDetection() {
  const [data, setData] = useState<FallView | null>(null);
  const [raw, setRaw] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const camera = useRef<Camera | null>(null);

  useEffect(() => {
    const abort = new AbortController();
    let viewTimer: ReturnType<typeof setTimeout>;
    let frameTimer: ReturnType<typeof setTimeout>;
    let objectUrl: string | null = null;
    let sequence = -1;
    const clearFrame = () => {
      if (objectUrl) URL.revokeObjectURL(objectUrl);
      objectUrl = null;
      setRaw(null);
      sequence = -1;
    };
    const pollView = async () => {
      try {
        const next = await api.fallView<FallView>(abort.signal);
        if (abort.signal.aborted) return;
        camera.current = next.camera;
        setData(next);
        setError("");
        if (next.camera.state !== "connected" || next.camera.analysis_enabled) clearFrame();
      } catch (err) {
        if (!abort.signal.aborted) {
          camera.current = null;
          setData(null);
          clearFrame();
          setError(err instanceof Error ? err.message : "Không kết nối được camera AI.");
        }
      } finally {
        if (!abort.signal.aborted) viewTimer = setTimeout(pollView, 500);
      }
    };
    const pollFrame = async () => {
      try {
        if (camera.current?.state === "connected" && !camera.current.analysis_enabled) {
          const response = await fetch(`${API_URL}/api/fall/frame?seq=${sequence}`, {
            signal: abort.signal, credentials: "include", cache: "no-store",
          });
          if (!response.ok) throw new Error("Không nhận được hình camera.");
          if (response.status === 200) {
            const blob = await response.blob();
            if (abort.signal.aborted || camera.current?.analysis_enabled || camera.current?.state !== "connected") return;
            const next = URL.createObjectURL(blob);
            const previous = objectUrl;
            objectUrl = next;
            setRaw(next);
            if (previous) URL.revokeObjectURL(previous);
            sequence = Number(response.headers.get("X-Frame-Sequence") ?? -1);
          }
        }
      } catch (err) {
        if (!abort.signal.aborted) {
          clearFrame();
          setError(err instanceof Error ? err.message : "Không nhận được hình camera.");
        }
      } finally {
        if (!abort.signal.aborted) frameTimer = setTimeout(pollFrame, 250);
      }
    };
    void pollView();
    void pollFrame();
    return () => {
      abort.abort(); clearTimeout(viewTimer); clearTimeout(frameTimer);
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, []);

  async function action(command: "start" | "stop" | "analysis" | "telegram/test", enabled?: boolean) {
    setBusy(true);
    try {
      await api.fallAction(command, enabled);
      const next = await api.fallView<FallView>();
      camera.current = next.camera;
      setData(next);
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Thao tác chưa thành công.");
    } finally { setBusy(false); }
  }

  const state = data?.camera;
  const analyzed = state?.state === "connected" && state.analysis_enabled ? data?.view : null;
  const image = analyzed ? `data:image/jpeg;base64,${analyzed.image}` : state?.analysis_enabled ? null : raw;
  const tracks = analyzed?.tracks ?? [];
  const danger = tracks.some((track) => track.danger);

  return (
    <section className="card space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="card-title">Camera & phát hiện ngã</h2>
        <span className={`chip ${danger ? "bg-rose-500/15 text-rose-300" : "bg-brand-500/15 text-brand-400"}`}>
          {danger ? "CẢNH BÁO TÉ NGÃ" : STATES[state?.state ?? ""] ?? "Đang tải camera"}
        </span>
      </div>
      <div className="relative overflow-hidden rounded-xl bg-ink-950" style={{ aspectRatio: analyzed ? `${analyzed.width}/${analyzed.height}` : "16/9" }}>
        {image ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={image} alt="Camera giám sát phát hiện ngã" className="h-full w-full object-contain" />
        ) : (
          <div className="absolute inset-0 grid place-items-center px-4 text-center text-sm text-slate-400">
            <div><Video size={28} className="mx-auto mb-2" />
              {state?.analysis_enabled && state.state === "connected" ? "Đang chờ hình phân tích AI…" : STATES[state?.state ?? ""] ?? "Đang tải camera…"}
            </div>
          </div>
        )}
        {analyzed && (
          <svg className="pointer-events-none absolute inset-0 h-full w-full" viewBox={`0 0 ${analyzed.width} ${analyzed.height}`} aria-label="Kết quả nhận diện">
            {tracks.map((track) => {
              const [x1, y1, x2, y2] = track.box;
              const color = track.danger ? "#fb7185" : track.pending ? "#fbbf24" : "#34d399";
              const label = track.danger ? `NGÃ · #${track.id}` : track.pending ? `Xác nhận ${track.streak}/${state?.confirmations}` : track.state === "COLLECTING" ? `Pose ${track.window_frames}/${track.window_target || 32}` : `Người #${track.id}`;
              return <g key={track.id}>
                <rect x={x1 * analyzed.width} y={y1 * analyzed.height} width={(x2 - x1) * analyzed.width} height={(y2 - y1) * analyzed.height} fill="none" stroke={color} strokeWidth="3" />
                <text x={x1 * analyzed.width + 4} y={Math.max(18, y1 * analyzed.height - 7)} fill={color} stroke="#020617" strokeWidth="3" paintOrder="stroke" fontSize="17" fontWeight="bold">{label}</text>
              </g>;
            })}
          </svg>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <button className="btn-ghost" disabled={busy || !state?.configured || state.enabled} onClick={() => void action("start")}><Play size={15} />Bật camera</button>
        <button className="btn-ghost" disabled={busy || !state?.enabled} onClick={() => void action("stop")}><Square size={15} />Tắt camera</button>
        <label className="ml-auto flex items-center gap-2 text-sm">
          <input type="checkbox" checked={state?.analysis_enabled ?? false} disabled={busy || !state?.ready || !state.enabled} onChange={(event) => void action("analysis", event.target.checked)} />
          Phân tích AI
        </label>
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-400">
        <span>{state?.ready ? `AI sẵn sàng · ${state.gpu_name || state.ai_device || "CPU"}` : "AI chưa sẵn sàng"}</span>
        <span>Ngưỡng {Math.round((state?.threshold ?? .8) * 100)}% · {state?.confirmations ?? 3} cửa sổ xác nhận</span>
        <span>{tracks.length} người trong hình phân tích</span>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-white/5 pt-3">
        <div className="text-xs text-slate-400"><p>Telegram: {TELEGRAM[state?.telegram ?? ""] ?? "Đang kiểm tra"}</p><p className="mt-1">{state?.telegram_detail}</p></div>
        <button className="btn-ghost text-xs" disabled={busy || !state || state.telegram === "not_configured"} onClick={() => void action("telegram/test")}>Gửi tin thử</button>
      </div>
      {(error || state?.error) && <p role="alert" className="text-sm text-rose-300">{error || state?.error}</p>}
    </section>
  );
}
