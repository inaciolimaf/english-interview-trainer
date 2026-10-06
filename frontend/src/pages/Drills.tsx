import { useEffect, useRef, useState } from "react";
import { api, type DrillAttemptResult, type DrillItem, type DrillSummary } from "../api/client";
import { Recorder } from "../audio/recorder";

const KIND_TITLE: Record<DrillItem["kind"], string> = {
  pron_read: "Read aloud",
  grammar_rewrite: "Say it correctly",
  tech_explain: "Explain it",
};

type Phase = "idle" | "running" | "done";

export default function Drills() {
  const [summary, setSummary] = useState<DrillSummary | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [items, setItems] = useState<DrillItem[]>([]);
  const [index, setIndex] = useState(0);
  const [result, setResult] = useState<DrillAttemptResult | null>(null);
  const [final, setFinal] = useState<{ attempts: number; passed: number; items: number } | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.drillSummary().then(setSummary, (e) => setError(String(e)));
  }, [phase]);

  const start = async () => {
    setError(null);
    try {
      const s = await api.startDrillSession();
      setSessionId(s.id);
      setItems(s.items);
      setIndex(0);
      setResult(null);
      setPhase(s.items.length ? "running" : "idle");
      if (!s.items.length) setError("Nothing is due right now. Come back later or do an interview.");
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e));
    }
  };

  const next = async () => {
    setResult(null);
    if (index + 1 < items.length) {
      setIndex(index + 1);
    } else if (sessionId) {
      setFinal(await api.finishDrillSession(sessionId));
      setPhase("done");
    }
  };

  const item = items[index];

  return (
    <section className="narrow-wide">
      <h2>Drills</h2>

      {phase === "idle" && (
        <div className="card">
          {summary && (
            <p>
              <strong>{summary.due}</strong> drill(s) due · {summary.active} in practice · {summary.retired} mastered
              {summary.due === 0 && summary.next_due_at && (
                <span className="muted"> · next one {new Date(summary.next_due_at).toLocaleString()}</span>
              )}
            </p>
          )}
          <p className="muted small">
            A 5–10 minute session with the items that are due, hardest first. Drills come from the errors in your
            interviews; mastered ones retire automatically.
          </p>
          <button className="primary" onClick={start} disabled={summary?.due === 0}>
            Start drill session
          </button>
        </div>
      )}
      {error && <p className="error">{error}</p>}

      {phase === "running" && item && sessionId && (
        <div className="card drill">
          <header className="card-header">
            <span className="fb-kind">
              {KIND_TITLE[item.kind]} · {index + 1} of {items.length}
            </span>
            {item.lapses > 0 && <span className="muted small">missed {item.lapses}×</span>}
          </header>
          <DrillPrompt item={item} />
          {result ? (
            <AttemptFeedback result={result} item={item} onNext={next} last={index + 1 === items.length} />
          ) : (
            <RecordButton
              key={item.id}
              maxSeconds={item.kind === "tech_explain" ? 70 : 30}
              onRecorded={async (pcm) => {
                setError(null);
                try {
                  setResult(await api.drillAttempt(sessionId, item.id, pcm));
                } catch (e) {
                  setError(String(e instanceof Error ? e.message : e));
                }
              }}
            />
          )}
        </div>
      )}

      {phase === "done" && final && (
        <div className="card">
          <h3>Session done</h3>
          <p>
            {final.passed} of {final.attempts} attempts passed across {final.items} drill(s).
          </p>
          <button onClick={() => { setPhase("idle"); setFinal(null); }}>Back</button>
        </div>
      )}
    </section>
  );
}

function DrillPrompt({ item }: { item: DrillItem }) {
  if (item.kind === "pron_read") {
    return (
      <>
        <p className="muted">{item.prompt_text}</p>
        <p className="read-text">{item.target_text}</p>
      </>
    );
  }
  if (item.kind === "grammar_rewrite") {
    return (
      <>
        <p className="muted">You said this in an interview. Say the corrected version out loud:</p>
        <p className="read-text">
          <s>{item.prompt_text}</s>
        </p>
      </>
    );
  }
  return (
    <>
      <p className="read-text">{item.prompt_text}</p>
      <p className="muted small">Talk for 30 to 60 seconds.</p>
    </>
  );
}

function AttemptFeedback({ result, item, onNext, last }: { result: DrillAttemptResult; item: DrillItem; onNext: () => void; last: boolean }) {
  return (
    <div className={`attempt ${result.passed ? "passed" : "failed"}`} role="status">
      <p>
        <strong>{result.passed ? "✓ Passed" : "✗ Not yet"}</strong> — {result.feedback}
      </p>
      {item.kind === "grammar_rewrite" && <p className="small">Target: <strong>{item.target_text}</strong></p>}
      {result.transcript && <p className="muted small">We heard: “{result.transcript}”</p>}
      <p className="muted small">
        {result.passed ? `Next review in ${result.item.interval_days} day(s).` : "This one comes back soon."}
      </p>
      <button className="primary" onClick={onNext}>
        {last ? "Finish" : "Next"}
      </button>
    </div>
  );
}

function RecordButton({ onRecorded, maxSeconds }: { onRecorded: (pcm: ArrayBuffer) => Promise<void>; maxSeconds: number }) {
  const recorder = useRef<Recorder | null>(null);
  const [state, setState] = useState<"ready" | "recording" | "sending">("ready");
  const [seconds, setSeconds] = useState(0);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (state !== "recording") return;
    const started = Date.now();
    const id = window.setInterval(() => {
      const s = (Date.now() - started) / 1000;
      setSeconds(s);
      if (s >= maxSeconds) void stop();
    }, 200);
    return () => window.clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state]);

  const begin = async () => {
    setError(null);
    try {
      recorder.current = new Recorder();
      await recorder.current.start();
      setSeconds(0);
      setState("recording");
    } catch (e) {
      setError(`Microphone unavailable: ${String(e)}`);
    }
  };

  const stop = async () => {
    if (!recorder.current) return;
    setState("sending");
    const pcm = await recorder.current.stop();
    recorder.current = null;
    await onRecorded(pcm);
    setState("ready");
  };

  return (
    <div className="row-actions">
      {state === "ready" && (
        <button className="primary" onClick={begin}>
          ● Record
        </button>
      )}
      {state === "recording" && (
        <button className="ptt active" onClick={stop}>
          ■ Stop ({seconds.toFixed(0)} s)
        </button>
      )}
      {state === "sending" && <span className="muted">Checking…</span>}
      {error && <span className="error small">{error}</span>}
    </div>
  );
}
