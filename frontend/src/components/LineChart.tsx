import { useId, useRef, useState } from "react";

export interface Point {
  label: string; // x label (date or week)
  value: number | null;
}

interface Props {
  title: string;
  points: Point[];
  suffix?: string; // "%"
  domain?: [number, number]; // fixed y range (e.g. rubric 1–5)
  max?: number; // hard ceiling for the padded range (e.g. 100 for percentages)
  lowerIsBetter?: boolean;
}

function decimalsFor(range: number): number {
  return range < 1 ? 2 : range < 10 ? 1 : 0;
}

const W = 320;
const H = 140;
const PAD = { top: 12, right: 12, bottom: 22, left: 44 };

/** Single-series line chart: 2px line, 8px markers, crosshair + tooltip, table view. */
export default function LineChart({ title, points, suffix = "", domain, max, lowerIsBetter }: Props) {
  const [hover, setHover] = useState<number | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const tableId = useId();
  const values = points.map((p) => p.value).filter((v): v is number => v !== null);

  if (values.length === 0) {
    return (
      <figure className="chart">
        <figcaption>{title}</figcaption>
        <p className="muted small">No data yet.</p>
      </figure>
    );
  }

  let [lo, hi] = domain ?? [Math.min(...values), Math.max(...values)];
  if (!domain) {
    const pad = (hi - lo) * 0.15 || Math.abs(hi) * 0.1 || 1;
    lo = Math.max(0, lo - pad);
    hi = max !== undefined ? Math.min(max, hi + pad) : hi + pad;
  }
  const innerW = W - PAD.left - PAD.right;
  const innerH = H - PAD.top - PAD.bottom;
  const x = (i: number) => PAD.left + (points.length === 1 ? innerW / 2 : (i / (points.length - 1)) * innerW);
  const y = (v: number) => PAD.top + innerH - ((v - lo) / (hi - lo || 1)) * innerH;
  const ticks = [lo, (lo + hi) / 2, hi];
  // ticks: just enough precision for the visible range; values: one decimal under 100
  const tickDecimals = decimalsFor(hi - lo);
  const tickFormat = (v: number) => `${v.toFixed(tickDecimals)}${suffix}`;
  const format = (v: number) => `${v.toFixed(Math.abs(v) >= 100 ? 0 : 1)}${suffix}`;

  const path = points
    .map((p, i) => (p.value === null ? null : `${x(i)},${y(p.value)}`))
    .filter(Boolean)
    .map((c, i) => `${i === 0 ? "M" : "L"}${c}`)
    .join(" ");

  const onMove = (e: React.PointerEvent) => {
    const rect = svgRef.current?.getBoundingClientRect();
    if (!rect) return;
    const px = ((e.clientX - rect.left) / rect.width) * W;
    let best = 0;
    points.forEach((_, i) => {
      if (Math.abs(x(i) - px) < Math.abs(x(best) - px)) best = i;
    });
    setHover(best);
  };

  const last = values[values.length - 1];
  const first = values[0];
  const better = lowerIsBetter ? last < first : last > first;
  const direction = last > first ? "▲" : last < first ? "▼" : "=";
  const verdict = last === first ? "same as first" : better ? "better than first" : "worse than first";
  const hovered = hover !== null ? points[hover] : null;

  return (
    <figure className="chart">
      <figcaption>
        {title}
        <span className="chart-latest">
          {format(last)}
          {values.length > 1 && (
            <span className={`small ${last === first ? "muted" : better ? "trend-down" : "trend-up"}`}>
              {" "}
              {direction} {verdict}
            </span>
          )}
        </span>
      </figcaption>
      <div className="chart-plot">
        <svg
          ref={svgRef}
          viewBox={`0 0 ${W} ${H}`}
          role="img"
          aria-label={`${title}: ${points.map((p) => `${p.label} ${p.value === null ? "no data" : format(p.value)}`).join(", ")}`}
          aria-describedby={tableId}
          onPointerMove={onMove}
          onPointerLeave={() => setHover(null)}
        >
          {ticks.map((t) => (
            <g key={t}>
              <line x1={PAD.left} x2={W - PAD.right} y1={y(t)} y2={y(t)} className="chart-grid" />
              <text x={PAD.left - 6} y={y(t)} className="chart-tick" textAnchor="end" dominantBaseline="middle">
                {tickFormat(t)}
              </text>
            </g>
          ))}
          <text x={x(0)} y={H - 6} className="chart-tick" textAnchor={points.length === 1 ? "middle" : "start"}>
            {points[0].label}
          </text>
          {points.length > 1 && (
            <text x={x(points.length - 1)} y={H - 6} className="chart-tick" textAnchor="end">
              {points[points.length - 1].label}
            </text>
          )}
          {hover !== null && <line x1={x(hover)} x2={x(hover)} y1={PAD.top} y2={PAD.top + innerH} className="chart-crosshair" />}
          <path d={path} className="chart-line" />
          {points.map((p, i) =>
            p.value === null ? null : (
              <circle key={i} cx={x(i)} cy={y(p.value)} r={hover === i ? 5 : 4} className="chart-dot" />
            ),
          )}
        </svg>
        {hovered && hover !== null && (
          <div className="chart-tooltip" style={{ left: `${(x(hover) / W) * 100}%` }} role="status">
            <span className="muted">{hovered.label}</span>
            <strong>{hovered.value === null ? "—" : format(hovered.value)}</strong>
          </div>
        )}
      </div>
      <details className="chart-table">
        <summary className="small muted">Table</summary>
        <table id={tableId}>
          <tbody>
            {points.map((p, i) => (
              <tr key={i}>
                <th scope="row">{p.label}</th>
                <td>{p.value === null ? "—" : format(p.value)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </figure>
  );
}
