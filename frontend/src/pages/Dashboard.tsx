import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type Dashboard as DashboardData, type User } from "../api/client";
import { categoryLabel, categoryPhoneme } from "../components/ErrorCard";
import { errorText, plural, relative, shortDate, TYPE_LABEL } from "../components/format";
import Icon from "../components/Icon";
import LineChart, { type Point } from "../components/LineChart";
import Phoneme from "../components/Phoneme";
import Segmented from "../components/Segmented";
import Sparkline from "../components/Sparkline";

type MetricKey = "pronunciation_accuracy" | "grammar_per_100_words" | "overall" | "wpm" | "fillers_per_min";

const METRICS: { key: MetricKey; title: string; unit: string; suffix?: string; lowerIsBetter?: boolean; domain?: [number, number]; max?: number; digits: number }[] = [
  { key: "pronunciation_accuracy", title: "Pronunciation", unit: "words clear", suffix: "%", max: 100, digits: 0 },
  { key: "grammar_per_100_words", title: "Grammar", unit: "errors / 100 words", lowerIsBetter: true, digits: 1 },
  { key: "overall", title: "Rubric", unit: "average of 5", domain: [1, 5], digits: 1 },
  { key: "wpm", title: "Pace", unit: "words / min", digits: 0 },
  { key: "fillers_per_min", title: "Fillers", unit: "per minute", lowerIsBetter: true, digits: 1 },
];

const TREND: Record<string, { label: string; cls: string }> = {
  up: { label: "more often", cls: "worse" },
  down: { label: "less often", cls: "better" },
  flat: { label: "steady", cls: "soft" },
  new: { label: "new", cls: "worse" },
};

function greeting(): string {
  const h = new Date().getHours();
  return h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
}

function heat(rate: number, max: number): number {
  // square root spreads the low rates apart, so one outlier does not flatten the rest
  return max ? Math.min(4, Math.floor(Math.sqrt(rate / max) * 5)) : 0;
}

export default function Dashboard() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [user, setUser] = useState<User | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [byWeek, setByWeek] = useState(false);
  const [metric, setMetric] = useState<MetricKey>("pronunciation_accuracy");

  useEffect(() => {
    api.dashboard().then(setData, (e) => setError(errorText(e)));
    api.me().then(setUser, () => {});
  }, []);

  const series = (key: MetricKey): Point[] =>
    byWeek
      ? (data?.weekly ?? []).map((w) => ({ label: w.week, value: w[key] }))
      : (data?.sessions ?? []).map((s) => ({
          label: `${shortDate(s.date)}, ${new Date(s.date).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" })}`,
          value: s[key],
        }));

  const active = data?.recent_sessions.find((s) => s.status === "active");
  const maxRate = Math.max(0, ...(data?.phonemes ?? []).map((p) => p.error_rate));
  const current = METRICS.find((m) => m.key === metric)!;
  const maxTop = Math.max(1, ...(data?.top_errors ?? []).map((t) => Math.max(t.before_per_100_words, t.recent_per_100_words)));

  return (
    <section className="page wide today">
      <header className="today-hero">
        <h1>
          {greeting()}
          {user?.display_name ? `, ${user.display_name.split(" ")[0]}` : ""}.
        </h1>
        <p className="lede">
          {!data
            ? "Loading your practice…"
            : data.sessions.length === 0
              ? "Run your first mock interview. Every answer you give is checked for pronunciation, grammar and content, and the mistakes turn into short drills."
              : `${plural(data.sessions.length, "interview")} analyzed so far. Here is what to do next.`}
        </p>
      </header>

      {error && <p className="notice error">Could not load your progress: {error}</p>}

      {data && (
        <>
          <ol className="next-steps" aria-label="What to do next">
            {active && (
              <li className="step step-live">
                <span className="step-icon"><Icon name="mic" /></span>
                <div>
                  <strong>Finish your {TYPE_LABEL[active.type].toLowerCase()} interview</strong>
                  <span className="soft">Started {relative(active.started_at)}. It picks up where you stopped.</span>
                </div>
                <Link to={`/interviews/${active.id}`} className="btn primary">Resume</Link>
              </li>
            )}
            <li className={`step ${data.drills.due ? "step-due" : ""}`}>
              <span className="step-icon"><Icon name="drills" /></span>
              <div>
                <strong>{data.drills.due ? `${plural(data.drills.due, "drill")} due` : "No drills due"}</strong>
                <span className="soft">
                  {data.drills.due
                    ? "About 5–10 minutes, built from your own mistakes."
                    : data.drills.next_due_at
                      ? `Next one ${relative(data.drills.next_due_at)}. ${data.drills.retired} mastered so far.`
                      : "Drills appear after your first analyzed interview."}
                </span>
              </div>
              {data.drills.due > 0 && <Link to="/drills" className="btn primary">Start drills</Link>}
            </li>
            <li className="step">
              <span className="step-icon"><Icon name="plus" /></span>
              <div>
                <strong>Practice a new interview</strong>
                <span className="soft">Technical, system design or behavioral — 15 to 60 minutes.</span>
              </div>
              <Link to="/interviews/new" className={`btn ${active || data.drills.due ? "" : "primary"}`}>New interview</Link>
            </li>
          </ol>

          <section className="block">
            <header className="block-head">
              <h2>Progress</h2>
              {data.sessions.length > 0 && (
                <Segmented
                  label="Group by"
                  size="small"
                  value={byWeek ? "week" : "interview"}
                  options={[{ value: "interview", label: "By interview" }, { value: "week", label: "By week" }]}
                  onChange={(v) => setByWeek(v === "week")}
                />
              )}
            </header>
            {data.sessions.length === 0 ? (
              <p className="empty">Your scores show up here after the first interview with a report.</p>
            ) : (
              <>
                <div className="readouts" role="tablist" aria-label="Metric">
                  {METRICS.map((m) => {
                    const values = series(m.key).map((p) => p.value);
                    const last = [...values].reverse().find((v) => v !== null);
                    return (
                      <button
                        key={m.key}
                        type="button"
                        role="tab"
                        aria-selected={metric === m.key}
                        className="readout"
                        onClick={() => setMetric(m.key)}
                      >
                        <span className="readout-title">{m.title}</span>
                        <span className="readout-value">
                          {last == null ? "—" : `${last.toFixed(m.digits)}${m.suffix ?? ""}`}
                        </span>
                        <span className="readout-unit">{m.unit}</span>
                        <Sparkline values={values} />
                      </button>
                    );
                  })}
                </div>
                <div className="big-chart" role="tabpanel">
                  <LineChart
                    key={`${metric}-${byWeek}`}
                    wide
                    title={`${current.title} (${current.unit})`}
                    points={series(metric)}
                    suffix={current.suffix}
                    max={current.max}
                    domain={current.domain}
                    lowerIsBetter={current.lowerIsBetter}
                  />
                </div>
              </>
            )}
          </section>

          <div className="split">
            <section className="block">
              <header className="block-head">
                <h2>Recurring errors</h2>
                <span className="soft small">last 30 days, per 100 words</span>
              </header>
              {data.top_errors.length === 0 ? (
                <p className="empty">Nothing recurring yet.</p>
              ) : (
                <ol className="recurring">
                  {data.top_errors.map((t) => {
                    const ipa = categoryPhoneme(t.category);
                    return (
                      <li key={t.category}>
                        <Link to={`/errors?category=${encodeURIComponent(t.category)}&period=30`}>
                          {ipa ? <>Sound <Phoneme ipa={ipa} /></> : categoryLabel(t.category)}
                        </Link>
                        <span className={`trend ${TREND[t.trend].cls}`}>{TREND[t.trend].label}</span>
                        <span className="compare" aria-label={`${t.before_per_100_words} before, ${t.recent_per_100_words} recently`}>
                          <i className="before" style={{ width: `${(t.before_per_100_words / maxTop) * 100}%` }} />
                          <i className="recent" style={{ width: `${(t.recent_per_100_words / maxTop) * 100}%` }} />
                        </span>
                        <span className="soft small">{t.count}× in total</span>
                      </li>
                    );
                  })}
                </ol>
              )}
              {data.top_errors.length > 0 && (
                <p className="legend-line small soft">
                  <i className="before" /> before <i className="recent" /> last two weeks
                </p>
              )}
            </section>

            <section className="block">
              <header className="block-head">
                <h2>Overcome</h2>
              </header>
              {data.overcome.categories.length === 0 && data.overcome.retired_drills.length === 0 ? (
                <p className="empty">Mistakes that fade away, and drills you master, are collected here.</p>
              ) : (
                <ul className="overcome">
                  {data.overcome.categories.map((c) => (
                    <li key={c.category}>
                      <Icon name="check" />
                      <span>
                        {categoryLabel(c.category)}
                        <small>
                          {c.before_per_100_words} → {c.recent_per_100_words} per 100 words
                        </small>
                      </span>
                    </li>
                  ))}
                  {data.overcome.retired_drills.map((d) => (
                    <li key={d.id}>
                      <Icon name="check" />
                      <span>
                        Drill mastered
                        <small className="spoken">{d.focus ?? d.prompt_text}</small>
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </div>

          <section className="block">
            <header className="block-head">
              <h2>Sounds to work on</h2>
              <span className="soft small">error rate per sound, last 90 days — darker means more errors</span>
            </header>
            {data.phonemes.length === 0 ? (
              <p className="empty">No pronunciation data yet.</p>
            ) : (
              <ul className="phoneme-grid">
                {data.phonemes.map((p) => (
                  <li
                    key={p.phoneme}
                    className={`heat-${heat(p.error_rate, maxRate)}`}
                    title={`/${p.phoneme}/: ${p.errors} errors in ${p.occurrences} occurrences`}
                  >
                    <span className="ipa glyph">{p.phoneme}</span>
                    <span className="rate">{(p.error_rate * 100).toFixed(0)}%</span>
                    <span className="count">{p.errors}/{p.occurrences}</span>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="block">
            <header className="block-head">
              <h2>Recent interviews</h2>
              <Link to="/interviews" className="btn ghost small">All interviews</Link>
            </header>
            {data.recent_sessions.length === 0 ? (
              <p className="empty">No interviews yet.</p>
            ) : (
              <ul className="session-list">
                {data.recent_sessions.slice(0, 5).map((s) => (
                  <li key={s.id}>
                    <Link to={s.status === "active" ? `/interviews/${s.id}` : `/interviews/${s.id}/report`}>
                      <span className={`type-mark type-${s.type}`} aria-hidden="true" />
                      <span className="session-title">{TYPE_LABEL[s.type]}</span>
                      <span className="soft small">{new Date(s.started_at).toLocaleString("en-US", { dateStyle: "medium", timeStyle: "short" })}</span>
                      <span className="session-score">
                        {s.status === "active" ? <span className="tag live">In progress</span> : s.overall != null ? `${s.overall.toFixed(1)} / 5` : <span className="soft small">{s.status === "abandoned" ? "Abandoned" : "No score"}</span>}
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </>
      )}
    </section>
  );
}
