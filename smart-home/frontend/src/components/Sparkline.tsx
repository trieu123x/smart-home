"use client";

interface Props {
  /** Oldest first. Non-finite values are skipped. */
  values: (number | undefined)[];
  min?: number;
  max?: number;
  className?: string;
}

/** Tiny trend line drawn in `currentColor`; renders nothing below two points. */
export function Sparkline({ values, min, max, className }: Props) {
  const points = values.filter((value): value is number => Number.isFinite(value));
  if (points.length < 2) return null;

  const lo = min ?? Math.min(...points);
  const hi = max ?? Math.max(...points);
  const span = hi - lo || 1;
  const path = points
    .map((value, index) => {
      const x = (index / (points.length - 1)) * 100;
      const y = 30 - ((Math.min(hi, Math.max(lo, value)) - lo) / span) * 28;
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(" ");

  return (
    <svg
      viewBox="0 0 100 32"
      preserveAspectRatio="none"
      className={className}
      aria-hidden="true"
    >
      <polyline
        points={path}
        fill="none"
        stroke="currentColor"
        strokeWidth={1.5}
        strokeLinejoin="round"
        strokeLinecap="round"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}
