import { Video } from "lucide-react";

// Đặt NEXT_PUBLIC_VIDEO_URL trong .env.local (vd luồng MJPEG) để hiện video thật.
const VIDEO_URL = process.env.NEXT_PUBLIC_VIDEO_URL;

/** Khung dành cho camera / hệ thống thị giác máy tính (gắn video vào sau). */
export function VideoSlot() {
  return (
    <section className="card">
      <div className="flex items-center justify-between">
        <h2 className="card-title">Camera</h2>
        {VIDEO_URL && <span className="chip bg-brand-500/15 text-brand-400">Trực tiếp</span>}
      </div>
      <div className="mt-3 aspect-video overflow-hidden rounded-xl border border-dashed border-white/10 bg-ink-800">
        {VIDEO_URL ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={VIDEO_URL} alt="Luồng video camera" className="h-full w-full object-contain" />
        ) : (
          <div className="grid h-full place-items-center px-4 text-center text-sm text-slate-500">
            <div>
              <Video size={28} className="mx-auto mb-2 text-slate-600" />
              Khu vực video
              <p className="muted mt-1">Đặt NEXT_PUBLIC_VIDEO_URL trong .env.local để hiện luồng camera</p>
            </div>
          </div>
        )}
      </div>
    </section>
  );
}
