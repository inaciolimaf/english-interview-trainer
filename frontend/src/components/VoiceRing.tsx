import { useEffect, useRef } from "react";
import type { ServerState } from "../realtime/protocol";

const SIZE = 300;
const C = SIZE / 2;
const BARS = 64;
const R_IN = 92; // bars start here
const R_ARC = 138; // time arc
const ARC_LEN = 2 * Math.PI * R_ARC;

export type Voice = "you" | "interviewer" | "none";

/**
 * The room's centerpiece: radial bars that follow whoever is talking (amber = you,
 * plum = interviewer), a slow orbit while the interviewer thinks, and an outer arc
 * with the time left. Levels are read every frame, outside React.
 */
export default function VoiceRing({
  state, levels, remaining, total, label, sub,
}: {
  state: ServerState | "OFFLINE";
  levels: () => { mic: number; out: number };
  remaining: number | null;
  total: number;
  label: string;
  sub?: string;
}) {
  const barsRef = useRef<SVGGElement>(null);
  const voice: Voice = state === "SPEAKING" || state === "DUCKING" ? "interviewer" : state === "LISTENING" ? "you" : "none";
  const voiceRef = useRef(voice);
  voiceRef.current = voice;

  useEffect(() => {
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const lines = Array.from(barsRef.current?.querySelectorAll("line") ?? []);
    let raf = 0;
    let smooth = 0;
    const tick = (t: number) => {
      const l = levels();
      const v = voiceRef.current;
      const target = v === "interviewer" ? l.out : v === "you" ? l.mic : 0;
      smooth = target > smooth ? smooth + (target - smooth) * 0.5 : smooth * 0.9;
      lines.forEach((line, i) => {
        const a = (i / BARS) * Math.PI * 2 - Math.PI / 2;
        const wobble = reduce ? 0.6 : 0.55 + 0.45 * Math.sin(t / 180 + i * 1.7) * Math.sin(t / 470 + i * 0.6);
        const len = 4 + smooth * 34 * wobble;
        line.setAttribute("x1", String(C + Math.cos(a) * R_IN));
        line.setAttribute("y1", String(C + Math.sin(a) * R_IN));
        line.setAttribute("x2", String(C + Math.cos(a) * (R_IN + len)));
        line.setAttribute("y2", String(C + Math.sin(a) * (R_IN + len)));
      });
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [levels]);

  const fraction = remaining === null || total <= 0 ? 1 : Math.max(0, Math.min(1, remaining / total));
  const low = remaining !== null && remaining <= 120;

  return (
    <div className={`voice-ring voice-${voice} state-${state.toLowerCase()}`}>
      <svg viewBox={`0 0 ${SIZE} ${SIZE}`} aria-hidden="true">
        <circle cx={C} cy={C} r={R_ARC} className="ring-track" />
        <circle
          cx={C}
          cy={C}
          r={R_ARC}
          className={`ring-time ${low ? "low" : ""}`}
          strokeDasharray={`${ARC_LEN * fraction} ${ARC_LEN}`}
          transform={`rotate(-90 ${C} ${C})`}
        />
        <circle cx={C} cy={C} r={R_IN - 10} className="ring-core" />
        <circle cx={C} cy={C} r={R_IN - 4} className="ring-orbit" />
        <g ref={barsRef} className="ring-bars">
          {Array.from({ length: BARS }, (_, i) => (
            <line key={i} />
          ))}
        </g>
      </svg>
      <div className="ring-text" aria-live="polite">
        <strong>{label}</strong>
        {sub && <span>{sub}</span>}
      </div>
    </div>
  );
}
