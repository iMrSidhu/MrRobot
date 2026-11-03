import { useId } from 'react';

export type Point = { t: string; v: number };

/**
 * Minimal SVG line chart. It renders nothing fabricated: with fewer than two
 * observations it shows the collecting state instead of a flat or fake line.
 */
export default function LineChart({
  points,
  height = 132,
  accent = '#fce205',
  emptyLabel = 'Collecting observations.',
}: {
  points: Point[];
  height?: number;
  accent?: string;
  emptyLabel?: string;
}) {
  const gradientId = `fill-${useId().replace(/:/g, '')}`;
  const width = 640;
  const pad = 10;

  if (points.length < 2) {
    return (
      <div
        className="flex items-center justify-center border border-dashed border-zinc-800 font-mono text-[10px] text-zinc-500"
        style={{ height }}
      >
        {emptyLabel} {points.length === 1 ? 'One sample so far.' : ''}
      </div>
    );
  }

  const times = points.map((p) => new Date(p.t).getTime());
  const values = points.map((p) => p.v);
  const minT = Math.min(...times);
  const maxT = Math.max(...times);
  const minV = Math.min(...values);
  const maxV = Math.max(...values);
  const spanT = maxT - minT || 1;
  const spanV = maxV - minV || 1;

  const x = (t: number) => pad + ((t - minT) / spanT) * (width - pad * 2);
  const y = (v: number) => height - pad - ((v - minV) / spanV) * (height - pad * 2);
  const coords = points.map((p, i) => {
    const px = x(times[i] ?? minT);
    const py = y(p.v);
    return { px, py, original: p };
  });
  const line = coords.map((c, i) => `${i === 0 ? 'M' : 'L'}${c.px.toFixed(1)},${c.py.toFixed(1)}`).join(' ');
  const area = `${line} L${coords[coords.length - 1]?.px.toFixed(1)},${height - pad} L${coords[0]?.px.toFixed(1)},${height - pad} Z`;
  const last = coords[coords.length - 1];

  return (
    <figure className="space-y-1">
      <svg viewBox={`0 0 ${width} ${height}`} className="w-full" role="img" aria-label={`${points.length} star observations, latest ${values[values.length - 1]}`}>
        <defs>
          <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={accent} stopOpacity="0.28" />
            <stop offset="100%" stopColor={accent} stopOpacity="0" />
          </linearGradient>
        </defs>
        <path d={area} fill={`url(#${gradientId})`} />
        <path d={line} fill="none" stroke={accent} strokeWidth="1.6" strokeLinejoin="round" />
        {last && <circle cx={last.px} cy={last.py} r="2.6" fill={accent} />}
      </svg>
      <figcaption className="flex justify-between font-mono text-[9px] text-zinc-600">
        <span>{new Date(minT).toLocaleString()}</span>
        <span>{new Date(maxT).toLocaleString()}</span>
      </figcaption>
    </figure>
  );
}
