import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type Dashboard as DashboardData, type Health, type ServiceStatus } from "../api/client";
import { categoryLabel } from "../components/ErrorCard";
import LineChart, { type Point } from "../components/LineChart";

const TREND: Record<string, { icon: string; text: string }> = {
  up: { icon: "▲", text: "more frequent" },
  down: { icon: "▼", text: "less frequent" },
  flat: { icon: "▬", text: "stable" },
  new: { icon: "●", text: "new" },
};

function StatusRow({ label, status }: { label: string; status?: ServiceStatus }) {
  const icon = status === undefined ? "…" : status.ok ? "✅" : "❌";
  return (
    <li title={status?.error}>
      <span>{icon}</span> {label}
      {status && !status.ok && status.error && <span className="muted"> — {status.error}</span>}
    </li>
  );
}

function SystemStatus() {
  const [health, setHealth] = useState<Health | null>(null);
  const [apiError, setApiError] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      try {
        const h = await api.health();
        if (!cancelled) {
          setHealth(h);
          setApiError(null);
        }
      } catch (err) {
        if (!cancelled) setApiError(String(err));
      }
    };
    void poll();
    const id = setInterval(poll, 5000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);
  const allOk = health && !apiError && health.database.ok && health.model_server.ok;
  return (
    <details className="card status-card" open={!allOk}>
      <summary>System status {allOk ? "✅" : ""}</summary>
      <ul className="status">
        <StatusRow label="API" status={apiError ? { ok: false, error: apiError } : health?.api} />
        <StatusRow label="Database" status={apiError ? { ok: false } : health?.database} />
        <StatusRow label="Model server" status={apiError ? { ok: false } : health?.model_server} />
      </ul>
    </details>
  );
}

function heatColor(rate: number, max: number): string {
  const t = max ? rate / max : 0;
  const steps = ["--seq-100", "--seq-250", "--seq-400", "--seq-550", "--seq-700"];
  return `var(${steps[Math.min(steps.length - 1, Math.floor(t * steps.length))]})`;
}

export default function Dashboard() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [byWeek, setByWeek] = useState(false);

  useEffect(() => {
    api.dashboard().then(setData, (e) => setError(String(e)));
  }, []);

  const series = (key: "pronunciation_accuracy" | "grammar_per_100_words" | "overall" | "wpm" | "fillers_per_min"): Point[] =>
    byWeek
      ? (data?.weekly ?? []).map((w) => ({ label: w.week, value: w[key] }))
      : (data?.sessions ?? []).map((s) => ({ label: new Date(s.date).toLocaleDateString(), value: s[key] }));

  const maxRate = Math.max(0, ...(data?.phonemes ?? []).map((p) => p.error_rate));

  return (
    <section className="dashboard">
      <header className="card-header">
        <h2>Dashboard</h2>
        <Link to="/interviews/new" className="button primary">
          New interview
        </Link>
      </header>

      <SystemStatus />
      {error && <p className="error">{error}</p>}

      {data && (
        <>
          <div className="tiles">
            <div className="tile">
              <span className="muted small">Drills due</span>
              <strong>{data.drills.due}</strong>
              <Link to="/drills" className={`button ${data.drills.due ? "primary" : ""}`}>
                Start drill session
              </Link>
            </div>
            <div className="tile">
              <span className="muted small">Interviews with a report</span>
              <strong>{data.sessions.length}</strong>
            </div>
            <div className="tile">
              <span className="muted small">Drills mastered</span>
              <strong>{data.drills.retired}</strong>
              <span className="muted small">{data.drills.active} in practice</span>
            </div>
          </div>

          <div className="card">
            <header className="card-header">
              <h3>Progress</h3>
              <div className="segmented" role="radiogroup" aria-label="Group by">
                <button role="radio" aria-checked={!byWeek} className={!byWeek ? "on" : ""} onClick={() => setByWeek(false)}>
                  By interview
                </button>
                <button role="radio" aria-checked={byWeek} className={byWeek ? "on" : ""} onClick={() => setByWeek(true)}>
                  By week
                </button>
              </div>
            </header>
            {data.sessions.length === 0 ? (
              <p className="muted">Finish an interview to see your progress here.</p>
            ) : (
              <div className="chart-grid-layout">
                <LineChart title="Pronunciation accuracy" points={series("pronunciation_accuracy")} suffix="%" max={100} />
                <LineChart title="Grammar errors per 100 words" points={series("grammar_per_100_words")} lowerIsBetter />
                <LineChart title="Rubric average" points={series("overall")} domain={[1, 5]} />
                <LineChart title="Speaking rate (wpm)" points={series("wpm")} />
                <LineChart title="Fillers per minute" points={series("fillers_per_min")} lowerIsBetter />
              </div>
            )}
          </div>

          <div className="two-col">
            <div className="card">
              <h3>Top recurring errors <span className="muted small">(30 days)</span></h3>
              {data.top_errors.length === 0 ? (
                <p className="muted">Nothing recurring yet.</p>
              ) : (
                <ol className="plain top-errors">
                  {data.top_errors.map((t) => (
                    <li key={t.category}>
                      <Link to={`/errors?category=${encodeURIComponent(t.category)}`}>{categoryLabel(t.category)}</Link>{" "}
                      <span className="muted small">{t.count}×</span>{" "}
                      <span className={`trend trend-${t.trend}`} title={`${t.before_per_100_words} → ${t.recent_per_100_words} per 100 words`}>
                        {TREND[t.trend].icon} {TREND[t.trend].text}
                      </span>
                    </li>
                  ))}
                </ol>
              )}
            </div>
            <div className="card">
              <h3>Overcome</h3>
              {data.overcome.categories.length === 0 && data.overcome.retired_drills.length === 0 ? (
                <p className="muted">Keep practicing — errors that fade away show up here.</p>
              ) : (
                <ul className="plain">
                  {data.overcome.categories.map((c) => (
                    <li key={c.category}>
                      ✓ {categoryLabel(c.category)}{" "}
                      <span className="muted small">
                        {c.before_per_100_words} → {c.recent_per_100_words} per 100 words
                      </span>
                    </li>
                  ))}
                  {data.overcome.retired_drills.map((d) => (
                    <li key={d.id}>
                      ✓ Drill mastered: <span className="muted">{d.prompt_text}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>

          <div className="card">
            <h3>Phoneme error rate <span className="muted small">(90 days, darker = more errors)</span></h3>
            {data.phonemes.length === 0 ? (
              <p className="muted">No pronunciation data yet.</p>
            ) : (
              <ul className="heatmap">
                {data.phonemes.map((p) => (
                  <li
                    key={p.phoneme}
                    style={{ background: heatColor(p.error_rate, maxRate) }}
                    className={p.error_rate / (maxRate || 1) >= 0.6 ? "dark-cell" : ""}
                    title={`/${p.phoneme}/: ${p.errors} errors in ${p.occurrences} occurrences`}
                  >
                    <strong>/{p.phoneme}/</strong>
                    <span>{(p.error_rate * 100).toFixed(0)}%</span>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div className="card">
            <h3>Recent interviews</h3>
            {data.recent_sessions.length === 0 ? (
              <p className="muted">No interviews yet.</p>
            ) : (
              <ul className="list">
                {data.recent_sessions.map((s) => (
                  <li key={s.id} className="list-row">
                    <span>
                      {s.type.replace("_", " ")} <span className="muted small">{new Date(s.started_at).toLocaleString()} · {s.status}</span>
                    </span>
                    <span className="row-actions">
                      {s.overall != null && <span className="muted small">{s.overall.toFixed(1)} / 5</span>}
                      {s.status === "active" ? (
                        <Link to={`/interviews/${s.id}`}>Resume</Link>
                      ) : (
                        <Link to={`/interviews/${s.id}/report`}>Report</Link>
                      )}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </>
      )}
    </section>
  );
}
