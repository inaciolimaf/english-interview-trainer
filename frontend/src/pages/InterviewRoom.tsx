import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, type Session, type TurnTakingMode } from "../api/client";
import LiveFeedback from "../components/LiveFeedback";
import { InterviewClient } from "../realtime/client";
import type { LiveFeedbackItem, ServerMessage, ServerState } from "../realtime/protocol";

const HEADPHONES_KEY = "eit.headphonesNoticeSeen";

interface Entry {
  key: string;
  role: "interviewer" | "candidate";
  text: string;
  interrupted?: boolean;
  draft?: boolean;
}

type Latency = Extract<ServerMessage, { type: "latency" }>;

const STATE_LABEL: Record<ServerState, string> = {
  IDLE: "Waiting",
  LISTENING: "Listening",
  THINKING: "Thinking…",
  SPEAKING: "Interviewer speaking",
  DUCKING: "Interviewer speaking",
};

function formatTime(s: number): string {
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

function readFlag(key: string): boolean {
  try {
    return localStorage.getItem(key) === "1";
  } catch {
    return false;
  }
}

function writeFlag(key: string): void {
  try {
    localStorage.setItem(key, "1");
  } catch {
    // storage unavailable: the notice just shows again next time
  }
}

export default function InterviewRoom() {
  const { sessionId = "" } = useParams();
  const [session, setSession] = useState<Session | null>(null);
  const [phase, setPhase] = useState<"lobby" | "starting" | "live" | "ended">("lobby");
  const [showHeadphones, setShowHeadphones] = useState(() => !readFlag(HEADPHONES_KEY));
  const [serverState, setServerState] = useState<ServerState>("IDLE");
  const [connection, setConnection] = useState<string>("closed");
  const [entries, setEntries] = useState<Entry[]>([]);
  const [remaining, setRemaining] = useState<number | null>(null);
  const [latency, setLatency] = useState<Latency | null>(null);
  const [notice, setNotice] = useState<{ kind: "error" | "warning"; text: string } | null>(null);
  const [mode, setMode] = useState<TurnTakingMode>("auto");
  const [talking, setTalking] = useState(false);
  const [feedback, setFeedback] = useState<LiveFeedbackItem[]>([]);
  const clientRef = useRef<InterviewClient | null>(null);
  // server turn ids restart on every connection: map them to transcript entry keys
  const turnKeys = useRef(new Map<number, string>());
  const transcriptRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api.getSession(sessionId).then((s) => {
      setSession(s);
      if (s.status !== "active") setPhase("ended");
      setEntries(
        (s.turns ?? []).map((t) => ({
          key: t.id,
          role: t.role,
          text: t.role === "interviewer" ? t.spoken_text : t.full_text,
          interrupted: t.interrupted,
        })),
      );
    }, (err) => setNotice({ kind: "error", text: String(err) }));
    api.getSettings().then((s) => setMode(s.turn_taking_mode), () => {});
    return () => {
      void clientRef.current?.close();
    };
  }, [sessionId]);

  useEffect(() => {
    transcriptRef.current?.scrollTo({ top: transcriptRef.current.scrollHeight, behavior: "smooth" });
  }, [entries]);

  const updateCandidate = useCallback((text: string, draft: boolean) => {
    setEntries((prev) => {
      const last = prev[prev.length - 1];
      if (last?.role === "candidate") return [...prev.slice(0, -1), { ...last, text, draft }];
      return [...prev, { key: `c-${Date.now()}`, role: "candidate", text, draft }];
    });
  }, []);

  const onMessage = useCallback(
    (msg: ServerMessage) => {
      switch (msg.type) {
        case "transcript_partial":
          updateCandidate(msg.text, true);
          break;
        case "transcript_final":
          updateCandidate(msg.text, false);
          break;
        case "stop_playback": {
          const key = turnKeys.current.get(msg.turn_id);
          setEntries((prev) => prev.map((e) => (e.key === key ? { ...e, interrupted: true } : e)));
          break;
        }
        case "time":
          setRemaining(msg.remaining_s);
          break;
        case "latency":
          setLatency(msg);
          break;
        case "error":
        case "warning":
          setNotice({ kind: msg.type, text: msg.message });
          break;
        case "live_feedback":
          setFeedback(msg.items);
          break;
        case "session_ended":
          setPhase("ended");
          void clientRef.current?.close();
          clientRef.current = null;
          break;
      }
    },
    [updateCandidate],
  );

  const onSentencePlayed = useCallback((turnId: number, _idx: number, text: string) => {
    setNotice((n) => (n?.kind === "warning" ? null : n));
    let key = turnKeys.current.get(turnId);
    if (!key) {
      key = `i-${Date.now()}-${turnId}`;
      turnKeys.current.set(turnId, key);
    }
    const entryKey = key;
    setEntries((prev) => {
      const key = entryKey;
      const existing = prev.find((e) => e.key === key);
      if (existing) return prev.map((e) => (e.key === key ? { ...e, text: `${e.text} ${text}` } : e));
      return [...prev, { key, role: "interviewer", text }];
    });
  }, []);

  const join = async () => {
    setPhase("starting");
    setNotice(null);
    const client = new InterviewClient(sessionId, {
      onState: setServerState,
      onMessage,
      onSentencePlayed,
      onConnection: (status) => {
        if (status === "open") turnKeys.current.clear();
        setConnection(status);
      },
    });
    clientRef.current = client;
    try {
      await client.start();
      if (mode !== "auto") client.setMode(mode);
      setPhase("live");
    } catch (err) {
      setNotice({ kind: "error", text: `Could not start audio: ${String(err)}` });
      await client.close();
      clientRef.current = null;
      setPhase("lobby");
    }
  };

  const changeMode = (next: TurnTakingMode) => {
    setMode(next);
    clientRef.current?.setMode(next);
    api.patchSettings({ turn_taking_mode: next }).catch(() => {});
  };

  const end = async () => {
    clientRef.current?.endSession();
    window.setTimeout(() => void clientRef.current?.close(), 1500);
  };

  // Push-to-talk: hold Space
  useEffect(() => {
    if (phase !== "live" || mode !== "push_to_talk") return;
    const isTyping = (e: KeyboardEvent) => (e.target as HTMLElement)?.closest("input, textarea, select");
    const down = (e: KeyboardEvent) => {
      if (e.code !== "Space" || e.repeat || isTyping(e)) return;
      e.preventDefault();
      setTalking(true);
      clientRef.current?.pushToTalk(true);
    };
    const up = (e: KeyboardEvent) => {
      if (e.code !== "Space" || isTyping(e)) return;
      e.preventDefault();
      setTalking(false);
      clientRef.current?.pushToTalk(false);
    };
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    return () => {
      window.removeEventListener("keydown", down);
      window.removeEventListener("keyup", up);
    };
  }, [phase, mode]);

  const pttButton = (pressed: boolean) => {
    setTalking(pressed);
    clientRef.current?.pushToTalk(pressed);
  };

  return (
    <section className="room">
      <header className="room-header">
        <div>
          <h2>{session ? `${session.type.replace("_", " ")} interview` : "Interview"}</h2>
          {session && <span className="muted">{session.seniority} · {session.interviewer_style} interviewer</span>}
        </div>
        <div className="room-meta">
          {remaining !== null && <span className="pill">{formatTime(remaining)} left</span>}
          {phase === "live" && (
            <span className={`pill state-${serverState.toLowerCase()}`} aria-live="polite">
              {connection === "reconnecting" ? "Reconnecting…" : STATE_LABEL[serverState]}
            </span>
          )}
        </div>
      </header>

      {notice && (
        <p className={notice.kind} role="alert">
          {notice.text}
        </p>
      )}

      {phase === "lobby" && showHeadphones && (
        <div className="callout">
          <strong>Use headphones.</strong> The microphone stays open while the interviewer talks so you can
          interrupt. Without headphones the interviewer's voice can leak into the mic; Chrome's echo cancellation
          helps but is not perfect.
          <div className="actions">
            <button
              onClick={() => {
                writeFlag(HEADPHONES_KEY);
                setShowHeadphones(false);
              }}
            >
              Got it
            </button>
          </div>
        </div>
      )}

      {(phase === "lobby" || phase === "starting") && (
        <div className="lobby">
          <ModeToggle mode={mode} onChange={changeMode} />
          <button className="primary" onClick={join} disabled={phase === "starting" || showHeadphones}>
            {phase === "starting" ? "Connecting…" : entries.length ? "Rejoin interview" : "Join interview"}
          </button>
        </div>
      )}

      {phase === "live" && feedback.length > 0 && <LiveFeedback items={feedback} onClose={() => setFeedback([])} />}

      <div className="transcript" ref={transcriptRef}>
        {entries.map((e) => (
          <div key={e.key} className={`bubble ${e.role} ${e.draft ? "draft" : ""}`}>
            <span className="who">{e.role === "interviewer" ? "Interviewer" : "You"}</span>
            <p>
              {e.text}
              {e.interrupted && <span className="cut" title="You interrupted here">—</span>}
            </p>
          </div>
        ))}
        {phase === "live" && serverState === "THINKING" && <div className="bubble interviewer draft"><p>…</p></div>}
      </div>

      {phase === "live" && (
        <footer className="room-controls">
          <ModeToggle mode={mode} onChange={changeMode} />
          {mode === "push_to_talk" && (
            <button
              className={`ptt ${talking ? "active" : ""}`}
              onPointerDown={() => pttButton(true)}
              onPointerUp={() => pttButton(false)}
              onPointerLeave={() => talking && pttButton(false)}
            >
              {talking ? "Talking…" : "Hold Space (or this button) to talk"}
            </button>
          )}
          {latency && (
            <span className="muted small" title="End of your speech → first audio of the reply">
              last reply {(latency.total_ms / 1000).toFixed(1)} s
            </span>
          )}
          <button className="danger" onClick={end}>
            End interview
          </button>
        </footer>
      )}

      {phase === "ended" && (
        <p className="muted">
          This interview has ended. <Link to={`/interviews/${sessionId}/report`}>See the report</Link> ·{" "}
          <Link to="/interviews/new">Start another one</Link>
        </p>
      )}
    </section>
  );
}

function ModeToggle({ mode, onChange }: { mode: TurnTakingMode; onChange: (m: TurnTakingMode) => void }) {
  return (
    <div className="segmented" role="radiogroup" aria-label="Turn taking">
      <button role="radio" aria-checked={mode === "auto"} className={mode === "auto" ? "on" : ""} onClick={() => onChange("auto")}>
        Hands-free
      </button>
      <button
        role="radio"
        aria-checked={mode === "push_to_talk"}
        className={mode === "push_to_talk" ? "on" : ""}
        onClick={() => onChange("push_to_talk")}
      >
        Push-to-talk
      </button>
    </div>
  );
}
