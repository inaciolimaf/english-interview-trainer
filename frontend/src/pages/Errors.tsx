import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, type ErrorItem } from "../api/client";
import ErrorCard, { categoryLabel, KIND_LABEL } from "../components/ErrorCard";

const PERIODS: { value: string; label: string; days: number | null }[] = [
  { value: "7", label: "Last 7 days", days: 7 },
  { value: "30", label: "Last 30 days", days: 30 },
  { value: "90", label: "Last 90 days", days: 90 },
  { value: "all", label: "All time", days: null },
];
const PAGE = 30;

export default function Errors() {
  const [params, setParams] = useSearchParams();
  const kind = params.get("kind") ?? "";
  const category = params.get("category") ?? "";
  const period = params.get("period") ?? "30";
  const showDismissed = params.get("dismissed") === "1";

  const [items, setItems] = useState<ErrorItem[]>([]);
  const [total, setTotal] = useState(0);
  const [facets, setFacets] = useState<{ kind: string; category: string; count: number }[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const query = (offset: number): Record<string, string> => {
    const q: Record<string, string> = { limit: String(PAGE), offset: String(offset) };
    if (kind) q.kind = kind;
    if (category) q.category = category;
    const days = PERIODS.find((p) => p.value === period)?.days;
    if (days) q.since = new Date(Date.now() - days * 86_400_000).toISOString();
    if (!showDismissed) q.dismissed = "false";
    return q;
  };

  const load = async (offset = 0) => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.exploreErrors(query(offset));
      setItems((prev) => (offset ? [...prev, ...res.items] : res.items));
      setTotal(res.total);
      setFacets(res.categories);
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load(0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kind, category, period, showDismissed]);

  const set = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    if (key === "kind") next.delete("category");
    setParams(next, { replace: true });
  };

  const categories = facets.filter((f) => !kind || f.kind === kind);

  return (
    <section className="narrow-wide">
      <h2>Error explorer</h2>
      <div className="filters" role="group" aria-label="Filters">
        <label>
          Type
          <select value={kind} onChange={(e) => set("kind", e.target.value)}>
            <option value="">All types</option>
            {Object.entries(KIND_LABEL).map(([k, label]) => (
              <option key={k} value={k}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label>
          Category
          <select value={category} onChange={(e) => set("category", e.target.value)}>
            <option value="">All categories</option>
            {categories.map((f) => (
              <option key={f.category} value={f.category}>
                {categoryLabel(f.category)} ({f.count})
              </option>
            ))}
          </select>
        </label>
        <label>
          Period
          <select value={period} onChange={(e) => set("period", e.target.value)}>
            {PERIODS.map((p) => (
              <option key={p.value} value={p.value}>
                {p.label}
              </option>
            ))}
          </select>
        </label>
        <label className="checkbox">
          <input type="checkbox" checked={showDismissed} onChange={(e) => set("dismissed", e.target.checked ? "1" : "")} />
          Show “not an error”
        </label>
      </div>

      {error && <p className="error">{error}</p>}
      <p className="muted small">{total} error(s)</p>
      {items.map((e) => (
        <ErrorCard key={e.id} error={e} />
      ))}
      {items.length < total && (
        <button onClick={() => load(items.length)} disabled={loading}>
          {loading ? "Loading…" : "Load more"}
        </button>
      )}
      {!loading && total === 0 && <p className="muted">No errors match these filters.</p>}
    </section>
  );
}
