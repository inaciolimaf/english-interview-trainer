import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api, type DrillAttemptResult, type DrillItem, type DrillSummary } from "../api/client";
import { Recorder } from "../audio/recorder";
import { errorText, plural, relative } from "../components/format";
import Icon from "../components/Icon";
import LevelMeter from "../components/LevelMeter";
import Phoneme from "../components/Phoneme";
import Segmented from "../components/Segmented";
import { speak } from "../components/speech";

const KIND_TITLE: Record<DrillItem["kind"], string> = {
  pron_read: "Read aloud",
  grammar_rewrite: "Say it correctly",
  tech_explain: "Explain it",
};

type Phase = "idle" | "running" | "done";

/** Focus is a bare phoneme for reading drills ("æ") or a category ("gram:verb_tense"). */
function FocusLabel({ focus }: { focus: string | null }) {
  if (!focus) return null;
  if (!focus.includes(":")) return <>sound <Phoneme ipa={focus} /></>;
  const ipa = focus.match(/(?:phoneme|vowel):(.+)$/)?.[1];
  if (ipa) return <>sound <Phoneme ipa={ipa} /></>;
  return <>{focus.slice(focus.lastIndexOf(":") + 1).replaceAll("_", " ")}</>;
}

/** The word a reading drill is about: 'Read aloud, paying attention to "hash".' → hash */
function targetWord(item: DrillItem): string | null {
  return item.kind === "pron_read" ? item.prompt_text.match(/"([^"]+)"/)?.[1] ?? null : null;
}

export default function Drills() {
  const [summary, setSummary] = useState<DrillSummary | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [items, setItems] = useState<DrillItem[]>([]);
  const [index, setIndex] = useState(0);
  const [results, setResults] = useState<Record<string, boolean>>({});
  const [result, setResult] = useState<DrillAttemptResult | null>(null);
  const [final, setFinal] = useState<{ attempts: number; passed: number; items: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);

  useEffect(() => {
    if (phase !== "running") api.drillSummary().then(setSummary, (e) => setError(errorText(e)));
  }, [phase]);

  const start = async () => {
    setError(null);
    setStarting(true);
    try {
      const s = await api.startDrillSession();
      setSessionId(s.id);
      setItems(s.items);
      setIndex(0);
      setResults({});
      setResult(null);
      setPhase(s.items.length ? "running" : "idle");
      if (!s.items.length) setError("Nothing is due right now. Come back later, or do an interview to create new drills.");
    } catch (e) {
      setError(errorText(e));
    } finally {
      setStarting(false);
    }
  };

  const next = async () => {
    setResult(null);
    if (index + 1 < items.length) {
      setIndex(index + 1);
    } else if (sessionId) {
      try {
        setFinal(await api.finishDrillSession(sessionId));
      } catch (e) {
        setError(errorText(e));
      }
      setPhase("done");
    }
  };

  const item = items[index];

  return (
    <section className="page drills">
      <header className="page-head">
        <h1>Drills</h1>
        <p className="lede">Short spoken exercises built from your own mistakes. Items you get right come back less often; master one three times in a row over a week and it retires.</p>
      </header>

      {error && <p className="notice error">{error}</p>}

      {phase === "idle" && (
        <>
          <div className="drill-start">
            <div className="due-count">
              <strong>{summary?.due ?? "–"}</strong>
              <span>{summary?.due === 1 ? "drill due" : "drills due"}</span>
            </div>
            <div className="drill-start-text">
              {summary && summary.due > 0 && <p>A 5–10 minute session with the items that are due, the ones you miss most first.</p>}
              {summary && summary.due === 0 && (
                <p>
                  You are up to date.
                  {summary.next_due_at ? ` The next drill is due ${relative(summary.next_due_at)}.` : " Do an interview to create new drills."}
                </p>
              )}
              <p className="soft small">
                {summary ? `${summary.active} in practice · ${summary.retired} mastered` : "Loading…"}
              </p>
            </div>
            <button type="button" className="btn primary large" onClick={start} disabled={!summary?.due || starting}>
              <Icon name="mic" /> {starting ? "Preparing…" : "Start drill session"}
            </button>
          </div>
          <DrillLibrary />
        </>
      )}

      {phase === "running" && item && sessionId && (
        <div className="drill-run">
          <ol className="drill-steps" aria-label="Progress">
            {items.map((it, i) => (
              <li
                key={it.id}
                className={i === index ? "current" : it.id in results ? (results[it.id] ? "passed" : "failed") : ""}
                aria-current={i === index ? "step" : undefined}
              >
                <span>{i + 1}</span>
              </li>
            ))}
          </ol>

          <article className={`drill-card kind-${item.kind}`}>
            <header>
              <span className="drill-kind">{KIND_TITLE[item.kind]}</span>
              {item.focus && (
                <span className="soft small">
                  {targetWord(item) && <>“{targetWord(item)}”, </>}
                  <FocusLabel focus={item.focus} />
                </span>
              )}
              {item.lapses > 0 && <span className="tag">missed {item.lapses}×</span>}
            </header>
            <DrillPrompt item={item} />
            {result ? (
              <AttemptFeedback result={result} item={item} onNext={next} last={index + 1 === items.length} />
            ) : (
              <RecordPanel
                key={item.id}
                maxSeconds={item.kind === "tech_explain" ? 70 : 30}
                onRecorded={async (pcm) => {
                  setError(null);
                  try {
                    const r = await api.drillAttempt(sessionId, item.id, pcm);
                    setResult(r);
                    setResults((all) => ({ ...all, [item.id]: r.passed }));
                  } catch (e) {
                    setError(`Could not check this attempt: ${errorText(e)}`);
                  }
                }}
              />
            )}
          </article>
        </div>
      )}

      {phase === "done" && (
        <div className="drill-done">
          <Icon name="check" size={28} />
          <h2>Session done</h2>
          {final && (
            <p>
              {final.passed} of {plural(final.attempts, "attempt")} passed across {plural(final.items, "drill")}.
            </p>
          )}
          <div className="actions">
            <button type="button" className="btn primary" onClick={() => { setPhase("idle"); setFinal(null); }}>Back to drills</button>
            <Link to="/" className="btn">Today</Link>
          </div>
        </div>
      )}
    </section>
  );
}

function DrillPrompt({ item }: { item: DrillItem }) {
  if (item.kind === "pron_read") {
    return (
      <div className="drill-prompt">
        <p className="soft">{item.prompt_text}</p>
        <p className="read-text spoken">{item.target_text}</p>
        <button type="button" className="btn ghost small" onClick={() => void speak(item.target_text)}>
          <Icon name="speaker" size={14} /> Hear it first
        </button>
      </div>
    );
  }
  if (item.kind === "grammar_rewrite") {
    return (
      <div className="drill-prompt">
        <p className="soft">You said this in an interview. Say the corrected version out loud.</p>
        <p className="read-text spoken wrong">{item.prompt_text}</p>
      </div>
    );
  }
  return (
    <div className="drill-prompt">
      <p className="read-text">{item.prompt_text}</p>
      <p className="soft small">Talk for 30 to 60 seconds, as if the interviewer had just asked.</p>
    </div>
  );
}

function AttemptFeedback({ result, item, onNext, last }: { result: DrillAttemptResult; item: DrillItem; onNext: () => void; last: boolean }) {
  return (
    <div className={`attempt ${result.passed ? "passed" : "failed"}`} role="status">
      <p className="attempt-verdict">
        <Icon name={result.passed ? "check" : "close"} />
        <strong>{result.passed ? "Passed" : "Not yet"}</strong>
      </p>
      <p>{result.feedback}</p>
      {item.kind === "grammar_rewrite" && (
        <p className="attempt-target">
          <span className="soft small">Target</span> <span className="spoken">{item.target_text}</span>
        </p>
      )}
      {result.transcript && (
        <p className="attempt-heard">
          <span className="soft small">We heard</span> <span className="spoken">“{result.transcript}”</span>
        </p>
      )}
      <footer>
        <span className="soft small">
          {result.passed ? `Next review in ${plural(result.item.interval_days, "day")}.` : "This one comes back soon."}
        </span>
        <button type="button" className="btn primary" onClick={onNext} autoFocus>
          {last ? "Finish session" : "Next drill"} <Icon name="forward" size={16} />
        </button>
      </footer>
    </div>
  );
}

function RecordPanel({ onRecorded, maxSeconds }: { onRecorded: (pcm: ArrayBuffer) => Promise<void>; maxSeconds: number }) {
  const recorder = useRef<Recorder | null>(null);
  const [state, setState] = useState<"ready" | "recording" | "sending">("ready");
  const [seconds, setSeconds] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const onRecordedRef = useRef(onRecorded);
  onRecordedRef.current = onRecorded;

  const stop = useCallback(async () => {
    const r = recorder.current;
    if (!r) return;
    recorder.current = null;
    setState("sending");
    const pcm = await r.stop();
    await onRecordedRef.current(pcm);
    setState("ready");
  }, []);

  useEffect(() => {
    if (state !== "recording") return;
    const started = Date.now();
    const id = window.setInterval(() => {
      const s = (Date.now() - started) / 1000;
      setSeconds(s);
      if (s >= maxSeconds) void stop();
    }, 200);
    return () => window.clearInterval(id);
  }, [state, maxSeconds, stop]);

  useEffect(() => () => void recorder.current?.stop(), []);

  const begin = async () => {
    setError(null);
    try {
      const r = new Recorder();
      await r.start();
      recorder.current = r;
      setSeconds(0);
      setState("recording");
    } catch (e) {
      setError(`Microphone unavailable: ${errorText(e)}`);
    }
  };

  const read = useCallback(() => recorder.current?.level ?? 0, []);

  return (
    <div className={`record-panel ${state}`}>
      {state === "ready" && (
        <button type="button" className="record-btn" onClick={begin}>
          <span className="record-dot" />
          Record your answer
        </button>
      )}
      {state === "recording" && (
        <>
          <button type="button" className="record-btn recording" onClick={() => void stop()}>
            <Icon name="stop" size={16} /> Stop and check
          </button>
          <LevelMeter read={read} active />
          <span className="record-time">
            {seconds.toFixed(0)} s <span className="soft">/ {maxSeconds} s</span>
          </span>
        </>
      )}
      {state === "sending" && <span className="soft">Checking your attempt…</span>}
      {error && <p className="notice error small">{error}</p>}
    </div>
  );
}

function DrillLibrary() {
  const [tab, setTab] = useState<"active" | "retired">("active");
  const [items, setItems] = useState<DrillItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setItems(null);
    api.drillItems(tab).then(setItems, (e) => setError(errorText(e)));
  }, [tab]);

  const now = Date.now();

  return (
    <section className="block">
      <header className="block-head">
        <h2>Library</h2>
        <Segmented
          label="Drill status"
          size="small"
          value={tab}
          onChange={setTab}
          options={[{ value: "active", label: "In practice" }, { value: "retired", label: "Mastered" }]}
        />
      </header>
      {error && <p className="notice error">{error}</p>}
      {items === null && !error && <p className="soft">Loading…</p>}
      {items?.length === 0 && (
        <p className="empty">{tab === "active" ? "No drills yet. They are created from the mistakes in your interviews." : "Nothing mastered yet — keep going."}</p>
      )}
      {items && items.length > 0 && (
        <ul className="drill-library">
          {items.map((d) => {
            const due = new Date(d.due_at).getTime() <= now;
            return (
              <li key={d.id}>
                <span className={`drill-kind-mark kind-${d.kind}`}>{KIND_TITLE[d.kind]}</span>
                <span className="drill-text spoken">{d.kind === "pron_read" ? d.target_text : d.prompt_text}</span>
                <span className="drill-meta">
                  {(d.focus || targetWord(d)) && (
                    <span>
                      {targetWord(d) && <strong className="spoken">{targetWord(d)}</strong>}
                      {targetWord(d) && d.focus ? ", " : ""}
                      <FocusLabel focus={d.focus} />
                    </span>
                  )}
                  {d.retired ? (
                    <span className="better">Mastered</span>
                  ) : (
                    <span className={due ? "due" : "soft"}>{due ? "Due now" : `Due ${relative(d.due_at)}`}</span>
                  )}
                  <span className="soft">
                    {d.repetitions === 0 ? "new" : `every ${plural(Math.round(d.interval_days), "day")}`}
                    {d.lapses > 0 ? `, missed ${d.lapses}×` : ""}
                    {d.occurrences > 1 ? `, seen ${d.occurrences}× in interviews` : ""}
                  </span>
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
