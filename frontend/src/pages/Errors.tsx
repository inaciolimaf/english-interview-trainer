import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, type ErrorItem } from "../api/client";
import ErrorCard, { categoryLabel, categoryPhoneme, KIND_LABEL, KIND_ORDER } from "../components/ErrorCard";
import { errorText, plural } from "../components/format";
import Phoneme from "../components/Phoneme";
import Segmented from "../components/Segmented";

const PERIODS: { value: string; label: string; days: number | null }[] = [
  { value: "7", label: "7 days", days: 7 },
  { value: "30", label: "30 days", days: 30 },
  { value: "90", label: "90 days", days: 90 },
  { value: "all", label: "All time", days: null },
];
const PAGE = 30;

type Facet = { kind: string; category: string; count: number };

export default function Errors() {
  const [params, setParams] = useSearchParams();
  const kind = params.get("kind") ?? "";
  const category = params.get("category") ?? "";
  const period = params.get("period") ?? "30";
  const showDismissed = params.get("dismissed") === "1";

  const [items, setItems] = useState<ErrorItem[]>([]);
  const [total, setTotal] = useState(0);
  const [facets, setFacets] = useState<Facet[]>([]);
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
      setError(errorText(e));
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

  const pickCategory = (f: Facet) => {
    const next = new URLSearchParams(params);
    if (category === f.category) next.delete("category");
    else {
      next.set("category", f.category);
      next.set("kind", f.kind);
    }
    setParams(next, { replace: true });
  };

  // facet counts are all-time; they guide the choice, the list below is the filtered truth
  const kindCounts = new Map<string, number>();
  for (const f of facets) kindCounts.set(f.kind, (kindCounts.get(f.kind) ?? 0) + f.count);
  const categories = facets.filter((f) => !kind || f.kind === kind).slice(0, 30);

  return (
    <section className="page wide">
      <header className="page-head">
        <h1>Errors</h1>
        <p className="lede">Every mistake found in your answers. Filter by type, sound or rule, and replay your own recording.</p>
      </header>

      <div className="filter-bar">
        <div className="kind-chips" role="radiogroup" aria-label="Error type">
          <button type="button" role="radio" aria-checked={!kind} className="chip-btn" onClick={() => set("kind", "")}>
            All types
          </button>
          {KIND_ORDER.filter((k) => kindCounts.has(k)).map((k) => (
            <button key={k} type="button" role="radio" aria-checked={kind === k} className="chip-btn" onClick={() => set("kind", k)}>
              <span className={`kind-dot kind-${k}`} />
              {KIND_LABEL[k]}
              <span className="count">{kindCounts.get(k)}</span>
            </button>
          ))}
        </div>
        <Segmented label="Period" size="small" value={period} options={PERIODS} onChange={(v) => set("period", v)} />
        <label className="switch">
          <input type="checkbox" checked={showDismissed} onChange={(e) => set("dismissed", e.target.checked ? "1" : "")} />
          <span>Include “not an error”</span>
        </label>
      </div>

      <div className="explorer">
        <aside className="facets" aria-label="Categories">
          <h2>Categories</h2>
          {categories.length === 0 ? (
            <p className="soft small">No categories yet.</p>
          ) : (
            <ul>
              {categories.map((f) => {
                const ipa = categoryPhoneme(f.category);
                return (
                  <li key={f.category}>
                    <button type="button" aria-pressed={category === f.category} onClick={() => pickCategory(f)}>
                      <span className={`kind-dot kind-${f.kind}`} />
                      <span className="facet-name">{ipa ? <Phoneme ipa={ipa} /> : categoryLabel(f.category)}</span>
                      <span className="count">{f.count}</span>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </aside>

        <div className="explorer-list">
          {error && <p className="notice error">Could not load errors: {error}</p>}
          <p className="soft small result-count">
            {loading && items.length === 0 ? "Loading…" : plural(total, "error")}
            {category && (
              <>
                {" "}in <strong>{categoryLabel(category)}</strong>{" "}
                <button type="button" className="btn ghost small" onClick={() => set("category", "")}>Clear</button>
              </>
            )}
          </p>
          {items.map((e) => (
            <ErrorCard key={e.id} error={e} />
          ))}
          {items.length < total && (
            <button type="button" className="btn load-more" onClick={() => load(items.length)} disabled={loading}>
              {loading ? "Loading…" : `Show ${Math.min(PAGE, total - items.length)} more`}
            </button>
          )}
          {!loading && total === 0 && !error && (
            <p className="empty">{facets.length === 0 ? "No errors yet. They appear here after your first analyzed interview." : "No errors match these filters. Try a longer period."}</p>
          )}
        </div>
      </div>
    </section>
  );
}
