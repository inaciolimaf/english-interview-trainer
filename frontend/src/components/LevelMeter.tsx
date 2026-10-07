import { useEffect, useRef } from "react";

const BARS = 24;

/** Live microphone level as a row of bars; `read` is polled every animation frame. */
export default function LevelMeter({ read, active }: { read: () => number; active: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!active) return;
    let raf = 0;
    let smooth = 0;
    const tick = () => {
      smooth = Math.max(read(), smooth * 0.85);
      const lit = Math.round(smooth * BARS);
      ref.current?.querySelectorAll("i").forEach((bar, i) => bar.classList.toggle("lit", i < lit));
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => {
      cancelAnimationFrame(raf);
      ref.current?.querySelectorAll("i").forEach((bar) => bar.classList.remove("lit"));
    };
  }, [read, active]);
  return (
    <div className={`level-meter ${active ? "on" : ""}`} ref={ref} aria-hidden="true">
      {Array.from({ length: BARS }, (_, i) => (
        <i key={i} />
      ))}
    </div>
  );
}
