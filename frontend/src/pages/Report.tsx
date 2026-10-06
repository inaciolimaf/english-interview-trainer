import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, type ErrorItem, type Session, type Turn } from "../api/client";
import ErrorCard, { categoryLabel, KIND_LABEL } from "../components/ErrorCard";
import { playClip } from "../components/clip";

const POLL_MS = 2500;
const KIND_ORDER: ErrorItem["kind"][] = ["pronunciation", "grammar", "vocabulary", "technical", "fluency"];

/** Word quality from its lowest phone z-score (status colors + a non-color cue). */
function wordClass(z: number | null | undefined, hasError: boolean): string {
  if (hasError) return "w-error";
  if (z === null || z === undefined) return "";
  if (z < -1.5) return "w-weak";
  return "w-good";
}

export default function Report() {
  const { sessionId = "" } = useParams();
  const [session, setSession] = useState<Session | null>(null);
  const [errors, setErrors] = useState<ErrorItem[]>([]);
  const [failed, setFailed] = useState<string | null>(null);
  const [requested, setRequested] = useState(false);

  const load = useCallback(async () => {
    try {
      const [s, e] = await Promise.all([api.getSession(sessionId), api.sessionErrors(sessionId)]);
      setSession(s);
      setErrors(e);
      return s;
    } catch (err) {
      setFailed(String(err instanceof Error ? err.message : err));
      return null;
    }
  }, [sessionId]);

  useEffect(() => {
    let timer: number | undefined;
    let cancelled = false;
    const tick = async () => {
      const s = await load();
      if (cancelled) return;
      const pending = !s?.report || s.report.analysis_pending > 0;
      if (s && pending && s.status !== "active") timer = window.setTimeout(tick, POLL_MS);
    };
    void tick();
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [load, requested]);

  const errorsById = useMemo(() => new Map(errors.map((e) => [e.id, e])), [errors]);
  const visibleErrors = errors.filter((e) => !e.dismissed);

  if (failed) return <section><h2>Report</h2><p className="error">{failed}</p></section>;
  if (!session) return <section><h2>Report</h2><p className="muted">Loading…</p></section>;

  const report = session.report;
  const generate = async () => {
    await api.regenerateReport(sessionId);
    setRequested((r) => !r);
  };

  return (
    <section className="report narrow-wide">
      <header className="card-header">
        <div>
          <h2>{session.type.replace("_", " ")} interview — report</h2>
          <span className="muted small">
            {new Date(session.started_at).toLocaleString()} · {session.seniority} · {session.interviewer_style} interviewer ·{" "}
            {session.duration_min} min
          </span>
        </div>
        <div className="row-actions">
          {report && (
            <Link to={`/interviews/${sessionId}/coach`} className="button primary">
              ✨ Explain with AI
            </Link>
          )}
          {report && session.status !== "active" && (
            <button onClick={generate} className="small">
              Regenerate
            </button>
          )}
        </div>
      </header>

      {!report && session.status === "active" && (
        <p className="muted">This interview is still in progress. <Link to={`/interviews/${sessionId}`}>Back to the interview</Link></p>
      )}
      {!report && session.status !== "active" && (
        <div className="card">
          <p>Generating the report… it appears here when the analysis of every answer is done.</p>
          {session.status === "abandoned" && !requested && (
            <button className="primary" onClick={generate}>
              Generate report now
            </button>
          )}
        </div>
      )}

      {report && (
        <>
          {report.analysis_pending > 0 && <p className="warning">Still analyzing {report.analysis_pending} answer(s)…</p>}
          {report.no_answers && (
            <p className="warning">
              No answers were recorded in this interview, so there is nothing to evaluate. If you spoke, the
              interviewer did not register the end of your answer.
            </p>
          )}
          {!report.llm_ok && !report.no_answers && (
            <p className="warning">
              The written evaluation is missing{report.llm_error ? ` (${report.llm_error})` : ""}. Metrics and errors below are complete.
            </p>
          )}

          <div className="tiles">
            <Tile label="Overall" value={session.scores?.overall != null ? `${session.scores.overall.toFixed(1)} / 5` : "—"} />
            <Tile label="Pronunciation accuracy" value={report.pronunciation.accuracy != null ? `${report.pronunciation.accuracy.toFixed(0)}%` : "—"}
              hint={`${report.pronunciation.error_words} of ${report.pronunciation.scored_words} words with errors`} />
            <Tile label="Grammar errors" value={report.grammar_per_100_words != null ? report.grammar_per_100_words.toFixed(1) : "—"} hint="per 100 words" />
            <Tile label="Speaking rate" value={`${report.fluency.wpm.toFixed(0)} wpm`} hint={`${report.fluency.words} words`} />
            <Tile label="Fillers" value={`${report.fluency.fillers_per_min.toFixed(1)}/min`}
              hint={`${report.fluency.filler_count} total · ${report.fluency.long_pauses} long pause(s)`} />
          </div>

          {report.rubric.length > 0 && (
            <div className="card">
              <h3>Rubric</h3>
              <ul className="rubric">
                {report.rubric.map((r) => (
                  <li key={r.criterion}>
                    <div className="rubric-head">
                      <span>{r.label}</span>
                      <span className="rubric-score" aria-label={`${r.score} out of 5`}>
                        {[1, 2, 3, 4, 5].map((n) => (
                          <span key={n} className={n <= r.score ? "pip on" : "pip"} />
                        ))}
                        <strong>{r.score}</strong>
                      </span>
                    </div>
                    <p className="muted small">{r.justification}</p>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {(report.strengths.length > 0 || report.improvements.length > 0) && (
            <div className="two-col">
              <div className="card">
                <h3>Strengths</h3>
                <ul className="plain">{report.strengths.map((s, i) => <li key={i}>{s}</li>)}</ul>
              </div>
              <div className="card">
                <h3>Top 3 to improve</h3>
                <ol className="plain">{report.improvements.map((s, i) => <li key={i}>{s}</li>)}</ol>
              </div>
            </div>
          )}

          {report.better_answer && (
            <div className="card">
              <h3>A better answer</h3>
              <p className="muted small">Question: {report.better_answer.question}</p>
              <p className="muted small">You said: {report.better_answer.answer_summary}</p>
              <blockquote>{report.better_answer.improved_answer}</blockquote>
            </div>
          )}

          {report.interruptions && (
            <div className="card">
              <h3>How you interrupted</h3>
              {report.interruptions.assessment && <p>{report.interruptions.assessment}</p>}
              <ul className="plain">
                {report.interruptions.examples.map((ex, i) => (
                  <li key={i}>
                    “{ex.candidate_said}” — <span className="muted">{ex.advice}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}

      <div className="card">
        <h3>Transcript</h3>
        <p className="legend small muted">
          <span className="w-weak">unclear</span> · <span className="w-error">error ▶</span> (click to hear
          yourself) · unmarked words sounded fine
        </p>
        <div className="transcript-report">
          {(session.turns ?? []).map((t) => (
            <TurnView key={t.id} turn={t} errorsById={errorsById} />
          ))}
        </div>
      </div>

      <details className="card all-errors">
        <summary>
          <strong>All errors</strong> <span className="muted">({visibleErrors.length}, grouped)</span>
          {report && (
            <span className="muted small"> — the AI coach explains the important ones</span>
          )}
        </summary>
        {KIND_ORDER.map((kind) => {
          const list = errors.filter((e) => e.kind === kind);
          if (list.length === 0) return null;
          const groups = new Map<string, ErrorItem[]>();
          for (const e of list) groups.set(e.category, [...(groups.get(e.category) ?? []), e]);
          const sorted = [...groups.entries()].sort((a, b) => b[1].length - a[1].length);
          return (
            <div key={kind} className="error-kind">
              <h4>
                {KIND_LABEL[kind]} <span className="muted">({list.filter((e) => !e.dismissed).length})</span>
              </h4>
              {sorted.map(([category, items]) =>
                category === "pron:suspect" ? (
                  <p key={category} className="muted small suspects">
                    Unclear words ({items.length}): {[...new Set(items.map((e) => e.word))].join(", ")} — they come back in
                    reading drills.
                  </p>
                ) : (
                  <details key={category} className="error-group">
                    <summary>
                      {categoryLabel(category)} <span className="muted">· {items.filter((e) => !e.dismissed).length}×</span>
                      {items[0]?.word && <span className="muted small"> — e.g. {[...new Set(items.map((e) => e.word))].slice(0, 4).join(", ")}</span>}
                    </summary>
                    {items.map((e) => (
                      <ErrorCard key={e.id} error={e} onChange={(u) => setErrors((all) => all.map((x) => (x.id === u.id ? u : x)))} />
                    ))}
                  </details>
                ),
              )}
            </div>
          );
        })}
      </details>
    </section>
  );
}

function Tile({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="tile">
      <span className="muted small">{label}</span>
      <strong>{value}</strong>
      {hint && <span className="muted small">{hint}</span>}
    </div>
  );
}

function TurnView({ turn, errorsById }: { turn: Turn; errorsById: Map<string, ErrorItem> }) {
  if (turn.role === "interviewer") {
    return (
      <p className="t-interviewer">
        <span className="who">Interviewer</span> {turn.spoken_text}
        {turn.interrupted && <span className="cut">—</span>}
      </p>
    );
  }
  const words = turn.asr_words ?? [];
  const z = turn.metrics?.word_z ?? [];
  const wordErrors = turn.metrics?.word_errors ?? {};
  if (words.length === 0) {
    return <p className="t-candidate"><span className="who">You</span> {turn.full_text}</p>;
  }
  return (
    <p className="t-candidate">
      <span className="who">You</span>{" "}
      {words.map((w, i) => {
        const err = wordErrors[String(i)] ? errorsById.get(wordErrors[String(i)]) : undefined;
        const live = err && !err.dismissed && err.category !== "pron:suspect";
        const cls = wordClass(z[i], Boolean(live));
        if (live && err?.audio_url) {
          return (
            <span key={i}>
              <button className={`word ${cls}`} title={err.explanation ?? ""} onClick={() => playClip(err.audio_url!)}>
                {w.w}
              </button>{" "}
            </span>
          );
        }
        return <span key={i} className={cls}>{w.w} </span>;
      })}
    </p>
  );
}
