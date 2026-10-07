import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, type Session, type SessionType } from "../api/client";
import { errorText, plural, STYLE_LABEL, TYPE_LABEL } from "../components/format";
import Icon from "../components/Icon";
import Segmented from "../components/Segmented";

type TypeFilter = "all" | SessionType;
type StatusFilter = "all" | Session["status"];

const STATUS_LABEL: Record<Session["status"], string> = { active: "In progress", completed: "Completed", abandoned: "Abandoned" };

function monthKey(iso: string): string {
  return new Date(iso).toLocaleDateString("en-US", { month: "long", year: "numeric" });
}

function minutes(s: Session): string | null {
  if (!s.ended_at) return null;
  const m = Math.round((new Date(s.ended_at).getTime() - new Date(s.started_at).getTime()) / 60_000);
  return `${m} of ${s.duration_min} min`;
}

export default function History() {
  const [params, setParams] = useSearchParams();
  const type = (params.get("type") ?? "all") as TypeFilter;
  const status = (params.get("status") ?? "all") as StatusFilter;
  const [sessions, setSessions] = useState<Session[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.listSessions(100).then(setSessions, (e) => setError(errorText(e)));
  }, []);

  const set = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value === "all") next.delete(key);
    else next.set(key, value);
    setParams(next, { replace: true });
  };

  const shown = (sessions ?? []).filter((s) => (type === "all" || s.type === type) && (status === "all" || s.status === status));
  const months = new Map<string, Session[]>();
  for (const s of shown) months.set(monthKey(s.started_at), [...(months.get(monthKey(s.started_at)) ?? []), s]);

  return (
    <section className="page">
      <header className="page-head with-action">
        <div>
          <h1>History</h1>
          <p className="lede">Every interview you started, with its score and report.</p>
        </div>
        <Link to="/interviews/new" className="btn primary"><Icon name="plus" size={16} /> New interview</Link>
      </header>

      <div className="filter-bar">
        <Segmented
          label="Type"
          size="small"
          value={type}
          onChange={(v) => set("type", v)}
          options={[
            { value: "all", label: "All types" },
            { value: "technical", label: "Technical" },
            { value: "system_design", label: "System design" },
            { value: "behavioral", label: "Behavioral" },
          ]}
        />
        <Segmented
          label="Status"
          size="small"
          value={status}
          onChange={(v) => set("status", v)}
          options={[
            { value: "all", label: "Any status" },
            { value: "completed", label: "Completed" },
            { value: "active", label: "In progress" },
            { value: "abandoned", label: "Abandoned" },
          ]}
        />
      </div>

      {error && <p className="notice error">Could not load your interviews: {error}</p>}
      {sessions === null && !error && <p className="soft">Loading…</p>}
      {sessions?.length === 0 && (
        <div className="empty-state">
          <h2>No interviews yet</h2>
          <p className="soft">Your first mock interview takes 15 minutes. Afterwards you get a report and drills built from your mistakes.</p>
          <Link to="/interviews/new" className="btn primary">Start your first interview</Link>
        </div>
      )}
      {sessions && sessions.length > 0 && shown.length === 0 && <p className="empty">No interviews match these filters.</p>}

      {[...months.entries()].map(([month, list]) => (
        <section key={month} className="month">
          <h2>
            {month} <span className="soft small">{plural(list.length, "interview")}</span>
          </h2>
          <ul className="history-list">
            {list.map((s) => {
              const overall = s.scores?.overall;
              const target = s.status === "active" ? `/interviews/${s.id}` : `/interviews/${s.id}/report`;
              return (
                <li key={s.id}>
                  <Link to={target} className="history-row">
                    <span className="history-date">
                      <strong>{new Date(s.started_at).getDate()}</strong>
                      <span>{new Date(s.started_at).toLocaleDateString("en-US", { weekday: "short" })}</span>
                    </span>
                    <span className="history-main">
                      <span className="session-title">
                        <span className={`type-mark type-${s.type}`} aria-hidden="true" />
                        {TYPE_LABEL[s.type]}
                        {s.plan?.problem_title && <span className="soft"> — {s.plan.problem_title}</span>}
                      </span>
                      <span className="soft small">
                        {new Date(s.started_at).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" })}
                        {", "}
                        {STYLE_LABEL[s.interviewer_style]?.toLowerCase() ?? s.interviewer_style} interviewer
                        {minutes(s) ? `, ${minutes(s)}` : ""}
                      </span>
                    </span>
                    <span className="history-metrics">
                      {s.scores?.pronunciation_accuracy != null && (
                        <span title="Pronunciation accuracy">{s.scores.pronunciation_accuracy.toFixed(0)}% clear</span>
                      )}
                      {s.scores?.wpm ? <span title="Speaking rate">{s.scores.wpm.toFixed(0)} wpm</span> : null}
                    </span>
                    <span className="history-score">
                      {s.status === "active" ? (
                        <span className="tag live">{STATUS_LABEL.active}</span>
                      ) : overall != null ? (
                        <>
                          <strong>{overall.toFixed(1)}</strong>
                          <span className="soft small">/ 5</span>
                        </>
                      ) : (
                        <span className="tag">{s.report ? "No score" : STATUS_LABEL[s.status]}</span>
                      )}
                    </span>
                    <Icon name="forward" size={16} />
                  </Link>
                </li>
              );
            })}
          </ul>
        </section>
      ))}
    </section>
  );
}
