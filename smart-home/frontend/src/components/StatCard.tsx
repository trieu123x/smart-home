"use client";

import clsx from "clsx";
import type { LucideIcon } from "lucide-react";

type Tone = "default" | "good" | "warning" | "critical";

const TONES: Record<Tone, { icon: string; value: string }> = {
  default: { icon: "bg-white/5 text-slate-300", value: "text-white" },
  good: { icon: "bg-brand-500/15 text-brand-400", value: "text-white" },
  warning: { icon: "bg-amber-500/15 text-amber-400", value: "text-amber-300" },
  critical: { icon: "bg-rose-500/15 text-rose-400", value: "text-rose-300" },
};

interface Props {
  label: string;
  value: string;
  hint?: string;
  icon: LucideIcon;
  tone?: Tone;
}

export function StatCard({ label, value, hint, icon: Icon, tone = "default" }: Props) {
  const styles = TONES[tone];
  return (
    <div className="card flex items-start gap-4">
      <span className={clsx("grid h-11 w-11 shrink-0 place-items-center rounded-xl", styles.icon)}>
        <Icon size={20} />
      </span>
      <div className="min-w-0">
        <p className="muted">{label}</p>
        <p className={clsx("mt-1 text-2xl font-semibold tabular-nums", styles.value)}>{value}</p>
        {hint && <p className="muted mt-1 truncate">{hint}</p>}
      </div>
    </div>
  );
}
