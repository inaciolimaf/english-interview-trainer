import { Fragment, useEffect, useRef, useState, type ReactNode } from "react";
import { Link, useParams } from "react-router-dom";
import { api, type CoachMessage, type ErrorItem, type Session } from "../api/client";
import { Recorder } from "../audio/recorder";
import { playClip } from "../components/clip";
import { speak, stopSpeaking } from "../components/speech";

const QUICK_REPLIES = ["Next point", "Explain that more simply", "Give me an exercise", "Show me a better answer"];
const READ_ALOUD_KEY = "eit.coachReadAloud";

function readFlag(): boolean {
  try {
    return localStorage.getItem(READ_ALOUD_KEY) === "1";
  } catch {
    return false;
  }
}

/** Inline: **bold**, *italic*, [[clip:id]] (their recording), [[say:text]] (hear it right). */
function inline(text: string, clips: Map<string, string>, key: string): ReactNode[] {
  const parts = text.split(/(\*\*[^*]+\*\*|\*[^*\s][^*]*\*|\[\[clip:[^\]]+\]\]|\[\[say:[^\]]+\]\])/g);
  return parts.map((part, i) => {
    const k = `${key}-${i}`;
    if (part.startsWith("**") && part.endsWith("**")) return <strong key={k}>{part.slice(2, -2)}</strong>;
    if (part.length > 2 && part.startsWith("*") && part.endsWith("*")) return <em key={k}>{part.slice(1, -1)}</em>;
    const clip = part.match(/^\[\[clip:\s*([^\]\s]+)\s*\]\]$/);
    if (clip) {
      const url = clips.get(clip[1]);
      return url ? (
        <button key={k} className="chip-button" onClick={() => playClip(url)} title="Hear your recording">
          ▶ your voice
        </button>
      ) : null;
    }
    const say = part.match(/^\[\[say:([^\]]+)\]\]$/);
    if (say) {
      return (
        <button key={k} className="chip-button say" onClick={() => void speak(say[1])} title="Hear it said correctly">
          🔊 “{say[1].trim()}”
        </button>
      );
    }
    return <Fragment key={k}>{part}</Fragment>;
  });
}

/** Paragraphs and "- " bullet lists. */
function Rich({ text, clips }: { text: string; clips: Map<string, string> }) {
  const blocks = text.split(/\n{2,}/);
  return (
    <>
      {blocks.map((block, bi) => {
        const lines = block.split("\n").filter((l) => l.trim());
        if (lines.length && lines.every((l) => /^\s*[-•]\s+/.test(l))) {
          return (
            <ul key={bi}>
              {lines.map((l, li) => (
                <li key={li}>{inline(l.replace(/^\s*[-•]\s+/, ""), clips, `${bi}-${li}`)}</li>
              ))}
            </ul>
          );
        }
        return (
          <p key={bi}>
            {lines.map((l, li) => (
              <Fragment key={li}>
                {li > 0 && <br />}
                {inline(l, clips, `${bi}-${li}`)}
              </Fragment>
            ))}
          </p>
        );
      })}
    </>
  );
}

export default function Coach() {
  const { sessionId = "" } = useParams();
  const [session, setSession] = useState<Session | null>(null);
  const [messages, setMessages] = useState<CoachMessage[]>([]);
  const [streaming, setStreaming] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [clips, setClips] = useState<Map<string, string>>(new Map());
  const [readAloud, setReadAloud] = useState(readFlag);
  const [recording, setRecording] = useState<"idle" | "recording" | "transcribing">("idle");
  const recorder = useRef<Recorder | null>(null);
  const bottom = useRef<HTMLDivElement>(null);
  const started = useRef(false);
  const readAloudRef = useRef(readAloud);
  readAloudRef.current = readAloud;

  const send = async (message: string | null) => {
    if (streaming !== null) return;
    setError(null);
    stopSpeaking();
    if (message) setMessages((m) => [...m, { role: "user", content: message }]);
    setStreaming("");
    try {
      const full = await api.coachSend(sessionId, message, (piece) => setStreaming((s) => (s ?? "") + piece));
      setMessages((m) => [...m, { role: "assistant", content: full }]);
      if (readAloudRef.current) void speak(full);
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e));
    } finally {
      setStreaming(null);
    }
  };

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [s, history, errors] = await Promise.all([
          api.getSession(sessionId),
          api.coachHistory(sessionId),
          api.sessionErrors(sessionId),
        ]);
        if (cancelled) return;
        setSession(s);
        setMessages(history);
        setClips(new Map(errors.filter((e: ErrorItem) => e.audio_url).map((e) => [e.id, e.audio_url!])));
        if (history.length === 0 && s.report && !started.current) {
          started.current = true;
          void send(null); // start the debrief right away
        }
      } catch (e) {
        if (!cancelled) setError(String(e instanceof Error ? e.message : e));
      }
    })();
    return () => {
      cancelled = true;
      stopSpeaking();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, streaming]);

  const toggleReadAloud = () => {
    const next = !readAloud;
    setReadAloud(next);
    if (!next) stopSpeaking();
    try {
      localStorage.setItem(READ_ALOUD_KEY, next ? "1" : "0");
    } catch {
      // per-viewer convenience only
    }
  };

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const text = input.trim();
    if (!text) return;
    setInput("");
    void send(text);
  };

  const toggleMic = async () => {
    if (recording === "idle") {
      try {
        recorder.current = new Recorder();
        await recorder.current.start();
        setRecording("recording");
      } catch (e) {
        setError(`Microphone unavailable: ${String(e)}`);
      }
    } else if (recording === "recording" && recorder.current) {
      setRecording("transcribing");
      try {
        const pcm = await recorder.current.stop();
        const { text } = await api.transcribe(pcm);
        if (text.trim()) void send(text.trim());
      } catch (e) {
        setError(String(e instanceof Error ? e.message : e));
      } finally {
        recorder.current = null;
        setRecording("idle");
      }
    }
  };

  const restart = async () => {
    stopSpeaking();
    await api.coachReset(sessionId);
    setMessages([]);
    void send(null);
  };

  return (
    <section className="coach">
      <header className="card-header">
        <div>
          <h2>AI coach</h2>
          <span className="muted small">
            {session ? `${session.type.replace("_", " ")} interview · ` : ""}
            <Link to={`/interviews/${sessionId}/report`}>back to the report</Link>
          </span>
        </div>
        <div className="row-actions">
          <button className={`small ${readAloud ? "on-toggle" : ""}`} onClick={toggleReadAloud} aria-pressed={readAloud}>
            {readAloud ? "🔊 Reading aloud" : "🔈 Read aloud"}
          </button>
          {messages.length > 0 && (
            <button className="small" onClick={restart} disabled={streaming !== null}>
              Start over
            </button>
          )}
        </div>
      </header>

      {session && !session.report && <p className="warning">The report is not ready yet — come back in a moment.</p>}

      <div className="coach-thread">
        {messages.map((m, i) => (
          <div key={i} className={`coach-msg ${m.role}`}>
            {m.role === "assistant" ? (
              <>
                <Rich text={m.content} clips={clips} />
                <button className="link small" onClick={() => void speak(m.content)}>
                  🔊 Read this
                </button>
              </>
            ) : (
              <p>{m.content}</p>
            )}
          </div>
        ))}
        {streaming !== null && (
          <div className="coach-msg assistant">
            {streaming ? <Rich text={streaming} clips={clips} /> : <p className="muted">Thinking…</p>}
          </div>
        )}
        <div ref={bottom} />
      </div>

      {error && <p className="error">{error}</p>}

      <div className="quick-replies">
        {QUICK_REPLIES.map((q) => (
          <button key={q} className="small" disabled={streaming !== null || !session?.report} onClick={() => void send(q)}>
            {q}
          </button>
        ))}
      </div>
      <form className="coach-input" onSubmit={submit}>
        <button
          type="button"
          className={`mic ${recording === "recording" ? "active" : ""}`}
          onClick={toggleMic}
          disabled={recording === "transcribing" || streaming !== null}
          aria-label={recording === "recording" ? "Stop recording and send" : "Ask by voice"}
          title={recording === "recording" ? "Stop and send" : "Ask by voice"}
        >
          {recording === "recording" ? "■" : recording === "transcribing" ? "…" : "🎤"}
        </button>
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask anything about your interview…"
          disabled={streaming !== null || !session?.report}
        />
        <button className="primary" type="submit" disabled={!input.trim() || streaming !== null}>
          Send
        </button>
      </form>
    </section>
  );
}
