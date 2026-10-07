import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, type ErrorItem, type Session, type Turn } from "../api/client";
import ErrorCard, { categoryLabel, categoryPhoneme, KIND_LABEL, KIND_ORDER } from "../components/ErrorCard";
import { playClip } from "../components/clip";
import { errorText, longDate, plural, SENIORITY_LABEL, STYLE_LABEL, TYPE_LABEL } from "../components/format";
import Icon from "../components/Icon";
import Phoneme from "../components/Phoneme";
import ScoreDial from "../components/ScoreDial";

const POLL_MS = 2500;

/** Word quality from its lowest phone z-score (status colors + a non-color cue). */
function wordClass(z: number | null | undefined, hasError: boolean): string {
  if (hasError) return "w-error";
  if (z === null || z === undefined) return "";
  if (z < -1.5) return "w-weak";
  return "";
}

export default function Report() {
  const { sessionId = "" } = useParams();
  const [session, setSession] = useState<Session | null>(null);
  const [errors, setErrors] = useState<ErrorItem[]>([]);
  const [failed, setFailed] = useState<string | null>(null);
  const [requested, setRequested] = useState(false);
  const [kind, setKind] = useState<ErrorItem["kind"] | null>(null);

  const load = useCallback(async () => {
    try {
      const [s, e] = await Promise.all([api.getSession(sessionId), api.sessionErrors(sessionId)]);
      setSession(s);
      setErrors(e);
      return s;
    } catch (err) {
      setFailed(errorText(err));
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
  const kinds = KIND_ORDER.filter((k) => errors.some((e) => e.kind === k));
  const shownKind = kind && kinds.includes(kind) ? kind : kinds[0];

  if (failed) {
    return (
      <section className="page narrow">
        <header className="page-head"><h1>Report</h1></header>
        <p className="notice error">Could not load this report: {failed}</p>
      </section>
    );
  }
  if (!session) {
    return (
      <section className="page narrow">
        <header className="page-head"><h1>Report</h1></header>
        <p className="soft">Loading…</p>
      </section>
    );
  }

  const report = session.report;
  const generate = async () => {
    await api.regenerateReport(sessionId);
    setRequested((r) => !r);
  };
  const candidateTurns = (session.turns ?? []).filter((t) => t.role === "candidate");
  const analyzed = candidateTurns.filter((t) => t.analysis_status === "done" || t.analysis_status === "failed").length;

  return (
    <section className="page report">
      <header className="report-head">
        <div className="report-title">
          <Link to="/interviews" className="back-link"><Icon name="back" size={16} /> History</Link>
          <h1>{TYPE_LABEL[session.type]} interview</h1>
          <ul className="meta-list">
            <li>{longDate(session.started_at)}</li>
            <li>{SENIORITY_LABEL[session.seniority] ?? session.seniority}</li>
            <li>{STYLE_LABEL[session.interviewer_style] ?? session.interviewer_style} interviewer</li>
            <li>{session.duration_min} min</li>
          </ul>
          <div className="actions">
            {report && (
              <Link to={`/interviews/${sessionId}/coach`} className="btn primary">
                <Icon name="coach" /> Debrief with the coach
              </Link>
            )}
            {report && session.status !== "active" && (
              <button type="button" className="btn ghost" onClick={generate}>
                <Icon name="refresh" size={16} /> Regenerate
              </button>
            )}
          </div>
        </div>
        {report && <ScoreDial score={session.scores?.overall} />}
      </header>

      {!report && session.status === "active" && (
        <p className="notice">
          This interview is still in progress. <Link to={`/interviews/${sessionId}`}>Back to the interview</Link>
        </p>
      )}
      {!report && session.status !== "active" && (
        <div className="generating">
          <div className="progress-line" role="progressbar" aria-valuemin={0} aria-valuemax={candidateTurns.length} aria-valuenow={analyzed}>
            <i style={{ width: `${candidateTurns.length ? (analyzed / candidateTurns.length) * 100 : 10}%` }} />
          </div>
          <p>
            Writing the report… {candidateTurns.length > 0 && `${analyzed} of ${plural(candidateTurns.length, "answer")} analyzed.`} It appears here
            when every answer is done.
          </p>
          {session.status === "abandoned" && !requested && (
            <button type="button" className="btn primary" onClick={generate}>
              Generate the report now
            </button>
          )}
        </div>
      )}

      {report && (
        <>
          {report.analysis_pending > 0 && <p className="notice">Still analyzing {plural(report.analysis_pending, "answer")}…</p>}
          {report.no_answers && (
            <p className="notice warning">
              No answers were recorded in this interview, so there is nothing to evaluate. If you spoke, the interviewer did
              not register the end of your answer — try push-to-talk next time.
            </p>
          )}
          {!report.llm_ok && !report.no_answers && (
            <p className="notice warning">
              The written evaluation is missing{report.llm_error ? ` (${report.llm_error})` : ""}. Use Regenerate to try again;
              the metrics and errors below are complete.
            </p>
          )}

          <dl className="metric-strip">
            <div>
              <dt>Pronunciation</dt>
              <dd>{report.pronunciation.accuracy != null ? `${report.pronunciation.accuracy.toFixed(0)}%` : "—"}</dd>
              <span>{report.pronunciation.error_words} of {report.pronunciation.scored_words} words with errors</span>
            </div>
            <div>
              <dt>Grammar</dt>
              <dd>{report.grammar_per_100_words != null ? report.grammar_per_100_words.toFixed(1) : "—"}</dd>
              <span>errors per 100 words</span>
            </div>
            <div>
              <dt>Pace</dt>
              <dd>{report.fluency.wpm.toFixed(0)}</dd>
              <span>words per minute · {report.fluency.words} words</span>
            </div>
            <div>
              <dt>Fillers</dt>
              <dd>{report.fluency.fillers_per_min.toFixed(1)}</dd>
              <span>per minute · {report.fluency.filler_count} total, {plural(report.fluency.long_pauses, "long pause")}</span>
            </div>
          </dl>

          {report.rubric.length > 0 && (
            <section className="block">
              <h2>Rubric</h2>
              <ul className="rubric">
                {report.rubric.map((r) => (
                  <li key={r.criterion}>
                    <div className="rubric-head">
                      <span className="rubric-label">{r.label}</span>
                      <span className={`rubric-bar score-${r.score}`} role="img" aria-label={`${r.score} out of 5`}>
                        {[1, 2, 3, 4, 5].map((n) => <i key={n} className={n <= r.score ? "on" : ""} />)}
                      </span>
                      <strong>{r.score}</strong>
                    </div>
                    <p>{r.justification}</p>
                  </li>
                ))}
              </ul>
            </section>
          )}

          {(report.strengths.length > 0 || report.improvements.length > 0) && (
            <div className="split">
              <section className="block">
                <h2>What went well</h2>
                <ul className="marks good">
                  {report.strengths.map((s, i) => <li key={i}><Icon name="check" size={16} />{s}</li>)}
                </ul>
              </section>
              <section className="block">
                <h2>Three things to improve</h2>
                <ol className="marks improve">
                  {report.improvements.map((s, i) => <li key={i}><span className="n">{i + 1}</span>{s}</li>)}
                </ol>
              </section>
            </div>
          )}

          {report.better_answer && (
            <section className="block">
              <h2>A stronger answer</h2>
              <p className="question">
                <span className="speaker">Interviewer</span>
                <span className="spoken">{report.better_answer.question}</span>
              </p>
              <div className="compare-answers">
                <div className="answer yours">
                  <h3>What you said, in short</h3>
                  <p className="spoken">{report.better_answer.answer_summary}</p>
                </div>
                <div className="answer stronger">
                  <h3>A stronger version</h3>
                  <p className="spoken">{report.better_answer.improved_answer}</p>
                </div>
              </div>
            </section>
          )}

          {report.interruptions && (report.interruptions.assessment || report.interruptions.examples.length > 0) && (
            <section className="block">
              <h2>How you interrupted</h2>
              {report.interruptions.assessment && <p className="reading">{report.interruptions.assessment}</p>}
              <ul className="interruptions">
                {report.interruptions.examples.map((ex, i) => (
                  <li key={i}>
                    <span className="spoken">“{ex.candidate_said}”</span>
                    <span className="soft">{ex.advice}</span>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </>
      )}

      <section className="block">
        <header className="block-head">
          <h2>Transcript</h2>
          <p className="legend-line small soft">
            <span className="w-weak">unclear</span> <span className="w-error">error</span> click an error to hear yourself
          </p>
        </header>
        {(session.turns ?? []).length === 0 ? (
          <p className="empty">Nothing was said in this interview.</p>
        ) : (
          <ol className="script report-script">
            {(session.turns ?? []).map((t) => (
              <TurnView key={t.id} turn={t} errorsById={errorsById} />
            ))}
          </ol>
        )}
      </section>

      <section className="block">
        <header className="block-head">
          <h2>All errors</h2>
          <span className="soft small">{plural(errors.filter((e) => !e.dismissed).length, "error")}, grouped by what went wrong</span>
        </header>
        {kinds.length === 0 ? (
          <p className="empty">{report ? "No errors found in this interview." : "Errors appear as answers are analyzed."}</p>
        ) : (
          <>
            <div className="tabs" role="tablist" aria-label="Error type">
              {kinds.map((k) => (
                <button key={k} type="button" role="tab" aria-selected={shownKind === k} onClick={() => setKind(k)}>
                  <span className={`kind-dot kind-${k}`} />
                  {KIND_LABEL[k]}
                  <span className="count">{errors.filter((e) => e.kind === k && !e.dismissed).length}</span>
                </button>
              ))}
            </div>
            {shownKind && (
              <ErrorGroups
                key={shownKind}
                errors={errors.filter((e) => e.kind === shownKind)}
                onChange={(u) => setErrors((all) => all.map((x) => (x.id === u.id ? u : x)))}
              />
            )}
          </>
        )}
      </section>
    </section>
  );
}

function ErrorGroups({ errors, onChange }: { errors: ErrorItem[]; onChange: (e: ErrorItem) => void }) {
  const groups = new Map<string, ErrorItem[]>();
  for (const e of errors) groups.set(e.category, [...(groups.get(e.category) ?? []), e]);
  const sorted = [...groups.entries()].sort((a, b) => b[1].length - a[1].length);
  return (
    <div className="error-groups" role="tabpanel">
      {sorted.map(([category, items]) => {
        const words = [...new Set(items.map((e) => e.word).filter(Boolean))];
        if (category === "pron:suspect") {
          return (
            <p key={category} className="suspects soft">
              Unclear words ({items.length}): <span className="spoken">{words.join(", ")}</span>. They come back in reading drills to check.
            </p>
          );
        }
        const ipa = categoryPhoneme(category);
        return (
          <details key={category} className="error-group" open={sorted.length <= 2}>
            <summary>
              <span className="group-name">{ipa ? <>Sound <Phoneme ipa={ipa} /></> : categoryLabel(category)}</span>
              <span className="count">{items.filter((e) => !e.dismissed).length}×</span>
              {words.length > 0 && <span className="soft small spoken">{words.slice(0, 4).join(", ")}</span>}
              <Icon name="chevron" size={16} />
            </summary>
            <div className="group-items">
              {items.map((e) => (
                <ErrorCard key={e.id} error={e} onChange={onChange} showKind={false} />
              ))}
            </div>
          </details>
        );
      })}
    </div>
  );
}

function TurnView({ turn, errorsById }: { turn: Turn; errorsById: Map<string, ErrorItem> }) {
  if (turn.role === "interviewer") {
    return (
      <li className="line interviewer">
        <span className="speaker">Interviewer</span>
        <p className="spoken">
          {turn.spoken_text}
          {turn.interrupted && <span className="cut">— interrupted</span>}
        </p>
      </li>
    );
  }
  const words = turn.asr_words ?? [];
  const z = turn.metrics?.word_z ?? [];
  const wordErrors = turn.metrics?.word_errors ?? {};
  return (
    <li className="line candidate">
      <span className="speaker">
        You
        {turn.metrics?.wpm ? <small>{Math.round(turn.metrics.wpm)} wpm</small> : null}
      </span>
      <p className="spoken">
        {words.length === 0
          ? turn.full_text
          : words.map((w, i) => {
              const err = wordErrors[String(i)] ? errorsById.get(wordErrors[String(i)]) : undefined;
              const live = err && !err.dismissed && err.category !== "pron:suspect";
              const cls = wordClass(z[i], Boolean(live));
              if (live && err?.audio_url) {
                return (
                  <span key={i}>
                    <button
                      type="button"
                      className={`word ${cls}`}
                      title={err.explanation ?? "Hear yourself"}
                      onClick={() => playClip(err.audio_url!)}
                    >
                      {w.w}
                    </button>{" "}
                  </span>
                );
              }
              return <span key={i} className={cls || undefined} title={live ? err?.explanation ?? undefined : undefined}>{w.w} </span>;
            })}
      </p>
    </li>
  );
}
