import { Fragment, useEffect, useRef, useState, type ReactNode } from "react";
import { Link, useParams } from "react-router-dom";
import { api, type CoachMessage, type ErrorItem, type Session } from "../api/client";
import { Recorder } from "../audio/recorder";
import { playClip } from "../components/clip";
import { errorText, readFlag as readStored, TYPE_LABEL, writeFlag } from "../components/format";
import Icon from "../components/Icon";
import LevelMeter from "../components/LevelMeter";
import { speak, stopSpeaking } from "../components/speech";

const QUICK_REPLIES = ["Next point", "Explain that more simply", "Give me an exercise", "Show me a better answer"];
const READ_ALOUD_KEY = "eit.coachReadAloud";

function readFlag(): boolean {
  return readStored(READ_ALOUD_KEY) === "1";
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
        <button key={k} type="button" className="inline-audio yours" onClick={() => playClip(url)} title="Hear your recording">
          <Icon name="play" size={12} /> your voice
        </button>
      ) : null;
    }
    const say = part.match(/^\[\[say:([^\]]+)\]\]$/);
    if (say) {
      return (
        <button key={k} type="button" className="inline-audio say" onClick={() => void speak(say[1])} title="Hear it said correctly">
          <Icon name="speaker" size={14} /> <span className="spoken">{say[1].trim()}</span>
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
      setError(errorText(e));
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
        if (!cancelled) setError(errorText(e));
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
    writeFlag(READ_ALOUD_KEY, next ? "1" : "0");
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
        setError(`Microphone unavailable: ${errorText(e)}`);
      }
    } else if (recording === "recording" && recorder.current) {
      setRecording("transcribing");
      try {
        const pcm = await recorder.current.stop();
        const { text } = await api.transcribe(pcm);
        if (text.trim()) void send(text.trim());
      } catch (e) {
        setError(errorText(e));
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

  const readLevel = () => recorder.current?.level ?? 0;
  const busy = streaming !== null;

  return (
    <section className="page coach">
      <header className="coach-head">
        <div>
          <Link to={`/interviews/${sessionId}/report`} className="back-link"><Icon name="back" size={16} /> Report</Link>
          <h1>Debrief</h1>
          <p className="soft">
            {session ? `Your coach walks through the ${TYPE_LABEL[session.type].toLowerCase()} interview, one point at a time.` : "Loading…"}
          </p>
        </div>
        <div className="actions">
          <button type="button" className={`btn ghost small ${readAloud ? "on" : ""}`} onClick={toggleReadAloud} aria-pressed={readAloud}>
            <Icon name="speaker" size={16} /> {readAloud ? "Reading replies aloud" : "Read replies aloud"}
          </button>
          {messages.length > 0 && (
            <button type="button" className="btn ghost small" onClick={restart} disabled={busy}>
              <Icon name="refresh" size={16} /> Start over
            </button>
          )}
        </div>
      </header>

      {session && !session.report && <p className="notice">The report is not ready yet, so the coach has nothing to go on. Come back when the report shows up.</p>}

      <div className="thread" aria-live="polite">
        {messages.map((m, i) => (
          <div key={i} className={`msg ${m.role}`}>
            <span className="speaker">{m.role === "assistant" ? "Coach" : "You"}</span>
            {m.role === "assistant" ? (
              <div className="msg-body">
                <Rich text={m.content} clips={clips} />
                <button type="button" className="btn ghost small" onClick={() => void speak(m.content)}>
                  <Icon name="speaker" size={14} /> Read this
                </button>
              </div>
            ) : (
              <div className="msg-body"><p>{m.content}</p></div>
            )}
          </div>
        ))}
        {streaming !== null && (
          <div className="msg assistant">
            <span className="speaker">Coach</span>
            <div className="msg-body">
              {streaming ? <Rich text={streaming} clips={clips} /> : <p className="dots" aria-label="Thinking"><i /><i /><i /></p>}
            </div>
          </div>
        )}
        <div ref={bottom} />
      </div>

      {error && <p className="notice error">{error}</p>}

      <div className="composer-bar">
        <div className="quick-replies">
          {QUICK_REPLIES.map((q) => (
            <button key={q} type="button" className="chip-btn" disabled={busy || !session?.report} onClick={() => void send(q)}>
              {q}
            </button>
          ))}
        </div>
        <form className="ask" onSubmit={submit}>
          <button
            type="button"
            className={`icon-btn mic ${recording === "recording" ? "recording" : ""}`}
            onClick={toggleMic}
            disabled={recording === "transcribing" || busy || !session?.report}
            aria-label={recording === "recording" ? "Stop recording and send" : "Ask by voice"}
            title={recording === "recording" ? "Stop and send" : "Ask by voice"}
          >
            <Icon name={recording === "recording" ? "stop" : "mic"} />
          </button>
          {recording === "idle" ? (
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Ask about any answer, word or mistake…"
              disabled={busy || !session?.report}
              aria-label="Your question"
            />
          ) : (
            <div className="ask-recording">
              <LevelMeter read={readLevel} active={recording === "recording"} />
              <span className="soft small">{recording === "recording" ? "Listening — click stop to send" : "Transcribing…"}</span>
            </div>
          )}
          <button className="btn primary" type="submit" disabled={!input.trim() || busy}>
            <Icon name="send" size={16} /> Send
          </button>
        </form>
      </div>
    </section>
  );
}
