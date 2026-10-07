export interface ServiceStatus {
  ok: boolean;
  error?: string;
}

export interface Health {
  api: ServiceStatus;
  database: ServiceStatus;
  model_server: ServiceStatus;
}

export type SessionType = "system_design" | "technical" | "behavioral";
export type TurnTakingMode = "auto" | "push_to_talk";

export interface Turn {
  id: string;
  idx: number;
  role: "interviewer" | "candidate";
  full_text: string;
  spoken_text: string;
  interrupted: boolean;
  interrupted_at_char: number | null;
  audio_ms: number | null;
  analysis_status?: "pending" | "done" | "failed" | null;
  metrics?: TurnMetrics | null;
  asr_words?: AsrWord[] | null;
}

export interface AsrWord {
  w: string;
  start_ms: number;
  end_ms: number;
  p: number;
}

export interface TurnMetrics {
  words?: number;
  wpm?: number;
  word_z?: (number | null)[];
  word_errors?: Record<string, string>;
}

export interface RubricScore {
  criterion: string;
  label: string;
  score: number;
  justification: string;
}

export interface Report {
  generated_at: string;
  llm_ok: boolean;
  llm_error?: string;
  no_answers?: boolean;
  rubric: RubricScore[];
  strengths: string[];
  improvements: string[];
  better_answer: { question: string; answer_summary: string; improved_answer: string } | null;
  interruptions: { assessment: string | null; examples: { candidate_said: string; advice: string }[] } | null;
  fluency: { words: number; speaking_s: number; wpm: number; filler_count: number; fillers_per_min: number; long_pauses: number };
  pronunciation: { scored_words: number; error_words: number; accuracy: number | null };
  errors_by_kind: Record<string, number>;
  grammar_per_100_words: number | null;
  analysis_pending: number;
}

export interface Scores {
  overall?: number | null;
  rubric?: Record<string, number>;
  pronunciation_accuracy: number | null;
  grammar_per_100_words: number | null;
  wpm: number;
  fillers_per_min: number;
}

export interface DashboardSession {
  session_id: string;
  date: string;
  type: SessionType;
  pronunciation_accuracy: number | null;
  grammar_per_100_words: number | null;
  overall: number | null;
  wpm: number | null;
  fillers_per_min: number | null;
}

export interface Dashboard {
  sessions: DashboardSession[];
  weekly: (Omit<DashboardSession, "session_id" | "date" | "type"> & { week: string; sessions: number })[];
  top_errors: { category: string; count: number; trend: "up" | "down" | "flat" | "new"; recent_per_100_words: number; before_per_100_words: number }[];
  overcome: {
    categories: { category: string; before_per_100_words: number; recent_per_100_words: number }[];
    retired_drills: { id: string; kind: DrillKind; focus: string | null; prompt_text: string }[];
  };
  phonemes: { phoneme: string; occurrences: number; errors: number; error_rate: number }[];
  drills: DrillSummary;
  recent_sessions: { id: string; type: SessionType; status: string; started_at: string; has_report: boolean; overall: number | null }[];
}

export type DrillKind = "pron_read" | "grammar_rewrite" | "tech_explain";

export interface DrillItem {
  id: string;
  kind: DrillKind;
  prompt_text: string;
  target_text: string;
  focus: string | null;
  interval_days: number;
  repetitions: number;
  lapses: number;
  due_at: string;
  retired: boolean;
  occurrences: number;
}

export interface DrillSummary {
  due: number;
  active: number;
  retired: number;
  next_due_at: string | null;
}

export interface DrillAttemptResult {
  passed: boolean;
  score: number;
  transcript: string;
  feedback: string;
  details: Record<string, unknown>;
  item: DrillItem;
}

export interface Role {
  title: string;
  company: string | null;
  start: string | null;
  end: string | null;
  highlights: string[];
}

export interface Project {
  name: string;
  description: string;
  impact: string | null;
  stack: string[];
}

export interface ParsedProfile {
  name: string | null;
  years_of_experience: number | null;
  stack: string[];
  roles: Role[];
  projects: Project[];
  achievements: string[];
}

export interface Resume {
  id: string;
  file_name: string;
  is_active: boolean;
  parsed_profile: ParsedProfile | null;
  created_at: string;
  text_chars: number;
  parse_error: string | null;
}

export interface ParsedJob {
  title: string | null;
  company: string | null;
  seniority: "junior" | "mid" | "senior" | "staff" | "unknown";
  required_stack: string[];
  nice_to_have: string[];
  responsibilities: string[];
  domain: string | null;
  summary: string | null;
}

export interface JobPosting {
  id: string;
  title: string;
  company: string | null;
  raw_text: string;
  parsed: ParsedJob | null;
  created_at: string;
  parse_error: string | null;
}

export interface ErrorItem {
  id: string;
  turn_id: string | null;
  kind: "pronunciation" | "grammar" | "technical" | "fluency" | "vocabulary";
  category: string;
  severity: "low" | "medium" | "high";
  original_text: string | null;
  corrected_text: string | null;
  explanation: string | null;
  word: string | null;
  expected_phonemes: string | null;
  heard_phonemes: string | null;
  phoneme_index: number | null;
  score: number | null;
  dismissed: boolean;
  audio_url: string | null;
  created_at: string;
}

export type Seniority = "mid" | "senior";
export type InterviewerStyle = "friendly" | "neutral" | "tough";
export type FeedbackMode = "live" | "end" | "hybrid";
export type Duration = 15 | 30 | 45 | 60;

export interface SessionCreate {
  type: SessionType;
  job_posting_id?: string | null;
  resume_id?: string | null;
  seniority?: Seniority;
  interviewer_style?: InterviewerStyle;
  duration_min?: Duration;
  feedback_mode?: FeedbackMode;
}

/** What the interview covers (interview_sessions.plan); the keys depend on the type. */
export interface SessionPlan {
  problem_id?: string;
  problem_title?: string;
  problem_statement?: string;
  deep_dives?: string[];
  stack?: string[];
  stack_source?: "job" | "resume" | "none";
  areas?: string[];
  themes?: string[];
  anchor_projects?: { name: string | null; description: string | null; impact: string | null }[];
}

export interface User {
  id: string;
  display_name: string;
  email: string | null;
}

export interface Session {
  id: string;
  type: SessionType;
  status: "active" | "completed" | "abandoned";
  seniority: string;
  interviewer_style: string;
  duration_min: number;
  feedback_mode: string;
  started_at: string;
  ended_at: string | null;
  job_posting_id: string | null;
  resume_id: string | null;
  plan: SessionPlan | null;
  report: Report | null;
  scores: Scores | null;
  turns?: Turn[];
}

export interface UserSettings {
  feedback_mode: FeedbackMode;
  default_interviewer_style: InterviewerStyle;
  default_seniority: Seniority;
  default_duration_min: Duration;
  turn_taking_mode: TurnTakingMode;
  end_of_turn_silence_ms: number;
  tts_voice: string;
  tts_speed: number;
  phoneme_threshold_k: number;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const isJson = typeof init?.body === "string";
  const res = await fetch(`/api${path}`, {
    ...init,
    headers: isJson ? { "Content-Type": "application/json", ...init?.headers } : init?.headers,
  });
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      // not JSON
    }
    throw new Error(detail);
  }
  return (res.status === 204 ? undefined : res.json()) as Promise<T>;
}

export interface CoachMessage {
  role: "user" | "assistant";
  content: string;
  at?: string;
}

/** POST that streams plain text back; calls onChunk with each piece, resolves with the full text. */
async function streamText(path: string, body: unknown, onChunk: (text: string) => void): Promise<string> {
  const res = await fetch(`/api${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok || !res.body) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const j = await res.json();
      if (typeof j.detail === "string") detail = j.detail;
    } catch {
      // not JSON
    }
    throw new Error(detail);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let full = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    const piece = decoder.decode(value, { stream: true });
    full += piece;
    onChunk(piece);
  }
  return full;
}

export const api = {
  health: () => request<Health>("/health"),
  me: () => request<User>("/users/me"),
  listSessions: (limit = 100) => request<Session[]>(`/sessions?limit=${limit}`),
  createSession: (body: SessionCreate) =>
    request<Session>("/sessions", { method: "POST", body: JSON.stringify(body) }),
  listResumes: () => request<Resume[]>("/resumes"),
  uploadResume: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<Resume>("/resumes", { method: "POST", body: form });
  },
  reparseResume: (id: string) => request<Resume>(`/resumes/${id}/reparse`, { method: "POST" }),
  activateResume: (id: string) => request<Resume>(`/resumes/${id}/activate`, { method: "POST" }),
  deleteResume: (id: string) => request<void>(`/resumes/${id}`, { method: "DELETE" }),
  listJobs: () => request<JobPosting[]>("/jobs"),
  createJob: (body: { raw_text: string; title?: string; company?: string }) =>
    request<JobPosting>("/jobs", { method: "POST", body: JSON.stringify(body) }),
  reparseJob: (id: string) => request<JobPosting>(`/jobs/${id}/reparse`, { method: "POST" }),
  deleteJob: (id: string) => request<void>(`/jobs/${id}`, { method: "DELETE" }),
  getSession: (id: string) => request<Session>(`/sessions/${id}`),
  sessionErrors: (id: string) => request<ErrorItem[]>(`/sessions/${id}/errors`),
  dismissError: (id: string) => request<ErrorItem>(`/errors/${id}/dismiss`, { method: "POST" }),
  coachHistory: (id: string) => request<CoachMessage[]>(`/sessions/${id}/coach`),
  coachSend: (id: string, message: string | null, onChunk: (t: string) => void) =>
    streamText(`/sessions/${id}/coach`, { message }, onChunk),
  coachReset: (id: string) => request<void>(`/sessions/${id}/coach`, { method: "DELETE" }),
  /** Interviewer voice; `voice`/`speed` override the saved settings (settings preview). */
  speak: async (text: string, opts: { voice?: string; speed?: number } = {}): Promise<Blob> => {
    const res = await fetch("/api/speech/tts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, ...opts }),
    });
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    return res.blob();
  },
  transcribe: (pcm: ArrayBuffer) =>
    request<{ text: string }>("/speech/stt", {
      method: "POST",
      body: pcm,
      headers: { "Content-Type": "application/octet-stream" },
    }),
  regenerateReport: (id: string) => request<{ status: string }>(`/sessions/${id}/report`, { method: "POST" }),
  dashboard: () => request<Dashboard>("/dashboard"),
  exploreErrors: (params: Record<string, string>) =>
    request<{ total: number; items: ErrorItem[]; categories: { kind: string; category: string; count: number }[] }>(
      `/errors?${new URLSearchParams(params)}`,
    ),
  drillSummary: () => request<DrillSummary>("/drills/summary"),
  drillItems: (status: "active" | "retired" | "all" = "active") => request<DrillItem[]>(`/drills/items?status=${status}`),
  startDrillSession: () =>
    request<{ id: string; started_at: string; items: DrillItem[]; estimated_s: number }>("/drills/sessions", { method: "POST" }),
  drillAttempt: (sessionId: string, itemId: string, pcm: ArrayBuffer) =>
    request<DrillAttemptResult>(`/drills/sessions/${sessionId}/attempts?item_id=${itemId}`, {
      method: "POST",
      body: pcm,
      headers: { "Content-Type": "application/octet-stream" },
    }),
  finishDrillSession: (sessionId: string) =>
    request<{ attempts: number; passed: number; items: number }>(`/drills/sessions/${sessionId}/finish`, { method: "POST" }),
  getSettings: () => request<UserSettings>("/settings"),
  patchSettings: (body: Partial<UserSettings>) =>
    request<UserSettings>("/settings", { method: "PATCH", body: JSON.stringify(body) }),
};
