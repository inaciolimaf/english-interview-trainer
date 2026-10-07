/** Tiny trend line for a metric readout (no axes; the number next to it carries the value). */
export default function Sparkline({ values }: { values: (number | null)[] }) {
  const v = values.filter((x): x is number => x !== null);
  if (v.length < 2) return <svg className="sparkline" viewBox="0 0 100 28" aria-hidden="true" />;
  const lo = Math.min(...v);
  const hi = Math.max(...v);
  const pts = v.map((x, i) => [(i / (v.length - 1)) * 96 + 2, 24 - ((x - lo) / (hi - lo || 1)) * 20]);
  const d = pts.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
  const [lx, ly] = pts[pts.length - 1];
  return (
    <svg className="sparkline" viewBox="0 0 100 28" aria-hidden="true">
      <path d={d} />
      <circle cx={lx} cy={ly} r={2.5} />
    </svg>
  );
}
