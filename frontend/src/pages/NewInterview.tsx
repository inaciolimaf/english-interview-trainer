import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  api,
  type Duration,
  type FeedbackMode,
  type InterviewerStyle,
  type JobPosting,
  type Resume,
  type Seniority,
  type SessionType,
} from "../api/client";

const TYPES: { value: SessionType; label: string; hint: string }[] = [
  { value: "technical", label: "Technical", hint: "Concepts, internals and trade-offs of the stack" },
  { value: "system_design", label: "System design", hint: "Design a system out loud, step by step" },
  { value: "behavioral", label: "Behavioral", hint: "STAR stories from your own projects" },
];
const STYLES: { value: InterviewerStyle; label: string; hint: string }[] = [
  { value: "friendly", label: "Friendly", hint: "Encouraging, gives hints" },
  { value: "neutral", label: "Neutral", hint: "Realistic, no hints" },
  { value: "tough", label: "Tough", hint: "Pushes back, cuts long answers" },
];
const FEEDBACK: { value: FeedbackMode; label: string }[] = [
  { value: "end", label: "At the end" },
  { value: "live", label: "Live" },
  { value: "hybrid", label: "Hybrid" },
];
const DURATIONS: Duration[] = [15, 30, 45, 60];
const JOB_SENIORITY: Record<string, Seniority | undefined> = { junior: "mid", mid: "mid", senior: "senior", staff: "senior" };

export default function NewInterview() {
  const navigate = useNavigate();
  const [type, setType] = useState<SessionType>("technical");
  const [jobs, setJobs] = useState<JobPosting[]>([]);
  const [jobId, setJobId] = useState<string>("");
  const [activeResume, setActiveResume] = useState<Resume | null | undefined>(undefined);
  const [seniority, setSeniority] = useState<Seniority>("senior");
  const [style, setStyle] = useState<InterviewerStyle>("neutral");
  const [duration, setDuration] = useState<Duration>(30);
  const [feedback, setFeedback] = useState<FeedbackMode>("end");
  const [defaultSeniority, setDefaultSeniority] = useState<Seniority>("senior");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.getSettings().then((s) => {
      setSeniority(s.default_seniority);
      setDefaultSeniority(s.default_seniority);
      setStyle(s.default_interviewer_style);
      setDuration(s.default_duration_min);
      setFeedback(s.feedback_mode);
    }, (e) => setError(String(e)));
    api.listJobs().then(setJobs, () => {});
    api.listResumes().then((rs) => setActiveResume(rs.find((r) => r.is_active) ?? null), () => setActiveResume(null));
  }, []);

  const pickJob = (id: string) => {
    setJobId(id);
    const job = jobs.find((j) => j.id === id);
    setSeniority(JOB_SENIORITY[job?.parsed?.seniority ?? ""] ?? defaultSeniority);
  };

  const start = async () => {
    setBusy(true);
    setError(null);
    try {
      const session = await api.createSession({
        type,
        job_posting_id: jobId || null,
        resume_id: activeResume?.id ?? null,
        seniority,
        interviewer_style: style,
        duration_min: duration,
        feedback_mode: feedback,
      });
      navigate(`/interviews/${session.id}`);
    } catch (err) {
      setError(String(err instanceof Error ? err.message : err));
      setBusy(false);
    }
  };

  return (
    <section className="narrow-wide">
      <h2>New interview</h2>

      <fieldset>
        <legend>Type</legend>
        <div className="choice-grid" role="radiogroup">
          {TYPES.map((t) => (
            <label key={t.value} className={`choice ${type === t.value ? "selected" : ""}`}>
              <input type="radio" name="type" checked={type === t.value} onChange={() => setType(t.value)} />
              <span className="choice-label">{t.label}</span>
              <span className="muted small">{t.hint}</span>
            </label>
          ))}
        </div>
      </fieldset>

      <fieldset>
        <legend>Context</legend>
        <div className="form-row">
          <label>
            Job posting
            <select value={jobId} onChange={(e) => pickJob(e.target.value)}>
              <option value="">None — general backend interview</option>
              {jobs.map((j) => (
                <option key={j.id} value={j.id}>
                  {j.title}
                  {j.company ? ` · ${j.company}` : ""}
                </option>
              ))}
            </select>
            <span className="muted small">
              <Link to="/jobs">Add a posting</Link>
            </span>
          </label>
          <label>
            Resume
            <span className="static-field">
              {activeResume === undefined
                ? "Loading…"
                : activeResume
                  ? activeResume.parsed_profile?.name ?? activeResume.file_name
                  : "No resume"}
            </span>
            <span className="muted small">
              <Link to="/profile">{activeResume ? "Change active resume" : "Upload a resume"}</Link>
            </span>
          </label>
        </div>
      </fieldset>

      <fieldset>
        <legend>Interviewer</legend>
        <div className="choice-grid" role="radiogroup">
          {STYLES.map((s) => (
            <label key={s.value} className={`choice ${style === s.value ? "selected" : ""}`}>
              <input type="radio" name="style" checked={style === s.value} onChange={() => setStyle(s.value)} />
              <span className="choice-label">{s.label}</span>
              <span className="muted small">{s.hint}</span>
            </label>
          ))}
        </div>
        <div className="form-row">
          <label>
            Seniority
            <select value={seniority} onChange={(e) => setSeniority(e.target.value as Seniority)}>
              <option value="mid">Mid-level</option>
              <option value="senior">Senior</option>
            </select>
          </label>
          <label>
            Duration
            <select value={duration} onChange={(e) => setDuration(Number(e.target.value) as Duration)}>
              {DURATIONS.map((d) => (
                <option key={d} value={d}>
                  {d} minutes
                </option>
              ))}
            </select>
          </label>
          <label>
            Feedback
            <select value={feedback} onChange={(e) => setFeedback(e.target.value as FeedbackMode)}>
              {FEEDBACK.map((f) => (
                <option key={f.value} value={f.value}>
                  {f.label}
                </option>
              ))}
            </select>
          </label>
        </div>
      </fieldset>

      {error && <p className="error">{error}</p>}
      <button className="primary" onClick={start} disabled={busy}>
        {busy ? "Creating…" : "Start interview"}
      </button>
    </section>
  );
}
