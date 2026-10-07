import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, type Session, type TurnTakingMode } from "../api/client";
import { Recorder } from "../audio/recorder";
import ConfirmButton from "../components/ConfirmButton";
import { clock, errorText, FEEDBACK_LABEL, readFlag, SENIORITY_LABEL, STYLE_LABEL, TYPE_LABEL, writeFlag } from "../components/format";
import Icon from "../components/Icon";
import LevelMeter from "../components/LevelMeter";
import LiveFeedback from "../components/LiveFeedback";
import PlanSummary from "../components/PlanSummary";
import Segmented from "../components/Segmented";
import VoiceRing from "../components/VoiceRing";
import { InterviewClient } from "../realtime/client";
import type { LiveFeedbackItem, ServerMessage, ServerState } from "../realtime/protocol";

const HEADPHONES_KEY = "eit.headphonesNoticeSeen";
const SILENT = () => ({ mic: 0, out: 0 });

interface Entry {
  key: string;
  role: "interviewer" | "candidate";
  text: string;
  interrupted?: boolean;
  draft?: boolean;
}

type Latency = Extract<ServerMessage, { type: "latency" }>;
type Phase = "loading" | "lobby" | "starting" | "live" | "ended";

const STATE_LABEL: Record<ServerState, string> = {
  IDLE: "Getting ready",
  LISTENING: "Listening",
  THINKING: "Thinking",
  SPEAKING: "Interviewer speaking",
  DUCKING: "Interviewer speaking",
};

const MODES: { value: TurnTakingMode; label: string }[] = [
  { value: "auto", label: "Hands-free" },
  { value: "push_to_talk", label: "Push-to-talk" },
];

export default function InterviewRoom() {
  const { sessionId = "" } = useParams();
  const [session, setSession] = useState<Session | null>(null);
  const [phase, setPhase] = useState<Phase>("loading");
  const [headphonesSeen, setHeadphonesSeen] = useState(() => readFlag(HEADPHONES_KEY) === "1");
  const [serverState, setServerState] = useState<ServerState>("IDLE");
  const [connection, setConnection] = useState<string>("closed");
  const [entries, setEntries] = useState<Entry[]>([]);
  const [remaining, setRemaining] = useState<number | null>(null);
  const [latency, setLatency] = useState<Latency | null>(null);
  const [notice, setNotice] = useState<{ kind: "error" | "warning"; text: string } | null>(null);
  const [mode, setMode] = useState<TurnTakingMode>("auto");
  const [talking, setTalking] = useState(false);
  const [feedback, setFeedback] = useState<LiveFeedbackItem[]>([]);
  const [ending, setEnding] = useState(false);
  const clientRef = useRef<InterviewClient | null>(null);
  // server turn ids restart on every connection: map them to transcript entry keys
  const turnKeys = useRef(new Map<number, string>());
  const scriptRef = useRef<HTMLOListElement>(null);

  useEffect(() => {
    api.getSession(sessionId).then((s) => {
      setSession(s);
      setPhase(s.status === "active" ? "lobby" : "ended");
      setEntries(
        (s.turns ?? []).map((t) => ({
          key: t.id,
          role: t.role,
          text: t.role === "interviewer" ? t.spoken_text : t.full_text,
          interrupted: t.interrupted,
        })),
      );
    }, (err) => {
      setNotice({ kind: "error", text: `Could not load this interview: ${errorText(err)}` });
      setPhase("lobby");
    });
    api.getSettings().then((s) => setMode(s.turn_taking_mode), () => {});
    return () => {
      void clientRef.current?.close();
    };
  }, [sessionId]);

  useEffect(() => {
    const el = scriptRef.current;
    el?.parentElement?.scrollTo({ top: el.parentElement.scrollHeight, behavior: "smooth" });
  }, [entries, serverState]);

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
      const existing = prev.find((e) => e.key === entryKey);
      if (existing) return prev.map((e) => (e.key === entryKey ? { ...e, text: `${e.text} ${text}` } : e));
      return [...prev, { key: entryKey, role: "interviewer", text }];
    });
  }, []);

  const join = async () => {
    setPhase("starting");
    setNotice(null);
    writeFlag(HEADPHONES_KEY, "1");
    setHeadphonesSeen(true);
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
      setNotice({ kind: "error", text: `Could not start the microphone or audio: ${errorText(err)}. Allow microphone access for this site and try again.` });
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

  const end = () => {
    setEnding(true);
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
      if (e.code !== "Space") return;
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

  const ptt = (pressed: boolean) => {
    setTalking(pressed);
    clientRef.current?.pushToTalk(pressed);
  };

  const levels = useCallback(() => clientRef.current?.levels() ?? SILENT(), []);

  const title = session ? `${TYPE_LABEL[session.type]} interview` : "Interview";
  const meta = session
    ? [SENIORITY_LABEL[session.seniority] ?? session.seniority, `${STYLE_LABEL[session.interviewer_style] ?? session.interviewer_style} interviewer`, `${session.duration_min} min`, `feedback ${FEEDBACK_LABEL[session.feedback_mode]?.toLowerCase() ?? session.feedback_mode}`]
    : [];

  const ringLabel =
    phase !== "live"
      ? phase === "starting" ? "Connecting" : "Not connected"
      : connection === "reconnecting" ? "Reconnecting" : ending ? "Wrapping up" : mode === "push_to_talk" && talking ? "Listening" : STATE_LABEL[serverState];

  return (
    <section className={`room phase-${phase}`}>
      <header className="room-head">
        <div>
          <Link to="/interviews" className="back-link"><Icon name="back" size={16} /> History</Link>
          <h1>{title}</h1>
          {meta.length > 0 && (
            <ul className="meta-list">
              {meta.map((m) => <li key={m}>{m}</li>)}
            </ul>
          )}
        </div>
      </header>

      {notice && (
        <p className={`notice ${notice.kind}`} role="alert">
          {notice.text}
        </p>
      )}

      {(phase === "lobby" || phase === "starting") && session && (
        <Lobby
          session={session}
          mode={mode}
          onMode={changeMode}
          onJoin={join}
          starting={phase === "starting"}
          rejoin={entries.length > 0}
          headphonesSeen={headphonesSeen}
        />
      )}

      {phase === "live" && (
        <div className="stage">
          <div className="stage-main">
            <VoiceRing
              state={connection === "reconnecting" ? "OFFLINE" : mode === "push_to_talk" && talking ? "LISTENING" : serverState}
              levels={levels}
              remaining={remaining}
              total={(session?.duration_min ?? 30) * 60}
              label={ringLabel}
              sub={remaining !== null ? `${clock(remaining)} left` : undefined}
            />

            <div className="script-scroll" aria-label="Conversation">
              <Script entries={entries} thinking={serverState === "THINKING"} listRef={scriptRef} />
            </div>

            <footer className="controls">
              <Segmented label="Turn taking" size="small" value={mode} options={MODES} onChange={changeMode} />
              {mode === "push_to_talk" ? (
                <button
                  type="button"
                  className={`ptt ${talking ? "held" : ""}`}
                  onPointerDown={() => ptt(true)}
                  onPointerUp={() => ptt(false)}
                  onPointerLeave={() => talking && ptt(false)}
                  onKeyDown={(e) => { if (e.key === "Enter" && !e.repeat) { e.preventDefault(); ptt(true); } }}
                  onKeyUp={(e) => { if (e.key === "Enter") ptt(false); }}
                  aria-pressed={talking}
                >
                  <Icon name="mic" size={20} />
                  {talking ? "Talking — release to send" : "Hold Space to talk"}
                </button>
              ) : (
                <span className="soft small controls-hint">Speak whenever you like. Pause to let the interviewer answer, or talk over them to interrupt.</span>
              )}
              <ConfirmButton confirm="End the interview now?" onConfirm={end} disabled={ending}>
                {ending ? "Ending…" : "End interview"}
              </ConfirmButton>
            </footer>
          </div>

          <aside className="stage-side">
            {feedback.length > 0 && <LiveFeedback items={feedback} onClose={() => setFeedback([])} />}
            {session && (
              <section className="side-block">
                <h3>What this interview covers</h3>
                <PlanSummary type={session.type} plan={session.plan} />
              </section>
            )}
            {latency && (
              <section className="side-block latency">
                <h3>Last reply</h3>
                <p>
                  <strong>{(latency.total_ms / 1000).toFixed(1)} s</strong> from the end of your answer to the interviewer's first word
                </p>
                <dl>
                  <dt>Waiting for you to finish</dt>
                  <dd>{(latency.end_of_turn_wait_ms / 1000).toFixed(1)} s</dd>
                  {latency.llm_first_token_ms != null && (
                    <>
                      <dt>First word of the reply</dt>
                      <dd>{(latency.llm_first_token_ms / 1000).toFixed(1)} s</dd>
                    </>
                  )}
                  {latency.first_audio_ms != null && (
                    <>
                      <dt>First audio</dt>
                      <dd>{(latency.first_audio_ms / 1000).toFixed(1)} s</dd>
                    </>
                  )}
                </dl>
              </section>
            )}
          </aside>
        </div>
      )}

      {phase === "ended" && (
        <div className="ended">
          <div className="ended-card">
            <Icon name="check" size={28} />
            <h2>Interview finished</h2>
            <p className="soft">
              {session?.report
                ? "The report is ready, with scores, a stronger answer and every mistake you made."
                : "Your answers are being analyzed. The report fills in as each answer is processed."}
            </p>
            <div className="actions">
              <Link to={`/interviews/${sessionId}/report`} className="btn primary">See the report</Link>
              <Link to="/interviews/new" className="btn">Start another interview</Link>
            </div>
          </div>
          {entries.length > 0 && (
            <div className="script-scroll ended-script">
              <Script entries={entries} thinking={false} />
            </div>
          )}
        </div>
      )}
    </section>
  );
}

function Script({ entries, thinking, listRef }: { entries: Entry[]; thinking: boolean; listRef?: React.Ref<HTMLOListElement> }) {
  if (entries.length === 0 && !thinking) {
    return <p className="soft script-empty">The conversation appears here as you talk.</p>;
  }
  return (
    <ol className="script" ref={listRef}>
      {entries.map((e) => (
        <li key={e.key} className={`line ${e.role} ${e.draft ? "draft" : ""}`}>
          <span className="speaker">{e.role === "interviewer" ? "Interviewer" : "You"}</span>
          <p className="spoken">
            {e.text}
            {e.interrupted && <span className="cut" title="You interrupted here">— interrupted</span>}
          </p>
        </li>
      ))}
      {thinking && (
        <li className="line interviewer thinking">
          <span className="speaker">Interviewer</span>
          <p className="dots" aria-label="Thinking"><i /><i /><i /></p>
        </li>
      )}
    </ol>
  );
}

function Lobby({
  session, mode, onMode, onJoin, starting, rejoin, headphonesSeen,
}: {
  session: Session;
  mode: TurnTakingMode;
  onMode: (m: TurnTakingMode) => void;
  onJoin: () => void;
  starting: boolean;
  rejoin: boolean;
  headphonesSeen: boolean;
}) {
  const recorder = useRef<Recorder | null>(null);
  const [testing, setTesting] = useState(false);
  const [micError, setMicError] = useState<string | null>(null);
  const [heard, setHeard] = useState(false);

  const stopTest = useCallback(async () => {
    const r = recorder.current;
    recorder.current = null;
    setTesting(false);
    if (r) await r.stop();
  }, []);

  useEffect(() => () => void stopTest(), [stopTest]);

  const toggleTest = async () => {
    if (testing) return stopTest();
    setMicError(null);
    try {
      const r = new Recorder();
      await r.start();
      recorder.current = r;
      setTesting(true);
    } catch (e) {
      setMicError(`Microphone unavailable: ${errorText(e)}`);
    }
  };

  const read = useCallback(() => {
    const level = recorder.current?.level ?? 0;
    if (level > 0.35) setHeard(true);
    return level;
  }, []);

  const join = async () => {
    await stopTest();
    onJoin();
  };

  return (
    <div className="lobby">
      <div className="lobby-checks">
        <section className={`check ${headphonesSeen ? "" : "attention"}`}>
          <Icon name="headphones" size={22} />
          <div>
            <h3>Wear headphones</h3>
            <p className="soft">
              The microphone stays open while the interviewer talks, so you can interrupt. Without headphones their voice
              can leak into the mic; echo cancellation helps but is not perfect.
            </p>
          </div>
        </section>

        <section className="check">
          <Icon name="mic" size={22} />
          <div>
            <h3>Check your microphone</h3>
            <p className="soft">Say a few words. The bars should move while you talk.</p>
            <div className="mic-test">
              <button type="button" className="btn small" onClick={toggleTest}>
                {testing ? <><Icon name="stop" size={14} /> Stop test</> : <><Icon name="mic" size={14} /> Test microphone</>}
              </button>
              <LevelMeter read={read} active={testing} />
              {testing && heard && <span className="better small"><Icon name="check" size={14} /> We can hear you</span>}
            </div>
            {micError && <p className="notice error small">{micError}</p>}
          </div>
        </section>

        <section className="check">
          <Icon name="clock" size={22} />
          <div>
            <h3>How you take turns</h3>
            <Segmented label="Turn taking" value={mode} options={MODES} onChange={onMode} />
            <p className="soft small">
              {mode === "auto"
                ? "Hands-free: the interviewer answers when you pause. Take your time — thinking pauses are fine."
                : "Push-to-talk: hold Space while you speak, release to send."}
            </p>
          </div>
        </section>

        <button type="button" className="btn primary large join" onClick={join} disabled={starting}>
          <Icon name="mic" /> {starting ? "Connecting…" : rejoin ? "Rejoin interview" : "Join interview"}
        </button>
      </div>

      <section className="lobby-plan">
        <h2>What this interview covers</h2>
        <PlanSummary type={session.type} plan={session.plan} />
      </section>
    </div>
  );
}
