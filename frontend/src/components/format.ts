import type { SessionType } from "../api/client";

export const TYPE_LABEL: Record<SessionType, string> = {
  technical: "Technical",
  system_design: "System design",
  behavioral: "Behavioral",
};

export const STYLE_LABEL: Record<string, string> = { friendly: "Friendly", neutral: "Neutral", tough: "Tough" };
export const SENIORITY_LABEL: Record<string, string> = { mid: "Mid-level", senior: "Senior" };
export const FEEDBACK_LABEL: Record<string, string> = { end: "At the end", live: "Live", hybrid: "Hybrid" };

export function errorText(e: unknown): string {
  return String(e instanceof Error ? e.message : e);
}

export function shortDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-US", { day: "numeric", month: "short" });
}

export function longDate(iso: string): string {
  return new Date(iso).toLocaleString("en-US", {
    weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit",
  });
}

/** "in 3 days", "2 hours ago", "today". */
export function relative(iso: string): string {
  const diff = new Date(iso).getTime() - Date.now();
  const rtf = new Intl.RelativeTimeFormat("en-US", { numeric: "auto" });
  const abs = Math.abs(diff);
  if (abs < 3_600_000) return rtf.format(Math.round(diff / 60_000), "minute");
  if (abs < 86_400_000) return rtf.format(Math.round(diff / 3_600_000), "hour");
  return rtf.format(Math.round(diff / 86_400_000), "day");
}

export function clock(s: number): string {
  return `${Math.floor(s / 60)}:${String(Math.max(0, s) % 60).padStart(2, "0")}`;
}

export function plural(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}

export function readFlag(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

export function writeFlag(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    // per-browser convenience only
  }
}
