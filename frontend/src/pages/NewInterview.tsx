import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
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
import { errorText } from "../components/format";
import Icon from "../components/Icon";
import Segmented from "../components/Segmented";

const TYPES: { value: SessionType; label: string; hint: string; sample: string }[] = [
  {
    value: "technical",
    label: "Technical",
    hint: "Concepts, internals and trade-offs of your stack.",
    sample: "“How does Postgres decide between an index scan and a sequential scan?”",
  },
  {
    value: "system_design",
    label: "System design",
    hint: "Design a system out loud, from requirements to bottlenecks.",
    sample: "“Design a URL shortener that handles 10,000 writes per second.”",
  },
  {
    value: "behavioral",
    label: "Behavioral",
    hint: "STAR stories anchored in your own projects.",
    sample: "“Tell me about a time you disagreed with a technical decision.”",
  },
];
const STYLES: { value: InterviewerStyle; label: string; hint: string }[] = [
  { value: "friendly", label: "Friendly", hint: "Encouraging, offers hints when you stall." },
  { value: "neutral", label: "Neutral", hint: "Realistic and even, no hints." },
  { value: "tough", label: "Tough", hint: "Pushes back and cuts long answers short." },
];
const FEEDBACK: { value: FeedbackMode; label: string; hint: string }[] = [
  { value: "end", label: "At the end", hint: "Nothing during the interview; the full report afterwards." },
  { value: "live", label: "Live", hint: "Silent notes on screen after each answer." },
  { value: "hybrid", label: "Hybrid", hint: "Only serious mistakes live; everything else in the report." },
];
const DURATIONS: Duration[] = [15, 30, 45, 60];
const JOB_SENIORITY: Record<string, Seniority | undefined> = { junior: "mid", mid: "mid", senior: "senior", staff: "senior" };

export default function NewInterview() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [type, setType] = useState<SessionType>("technical");
  const [jobs, setJobs] = useState<JobPosting[] | null>(null);
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
    const t = params.get("type");
    if (t === "technical" || t === "system_design" || t === "behavioral") setType(t);
    Promise.all([api.getSettings(), api.listJobs().catch(() => [] as JobPosting[])]).then(([s, js]) => {
      setStyle(s.default_interviewer_style);
      setDuration(s.default_duration_min);
      setFeedback(s.feedback_mode);
      setDefaultSeniority(s.default_seniority);
      setJobs(js);
      const wanted = js.find((j) => j.id === params.get("job"));
      setJobId(wanted?.id ?? "");
      setSeniority(JOB_SENIORITY[wanted?.parsed?.seniority ?? ""] ?? s.default_seniority);
    }, (e) => setError(errorText(e)));
    api.listResumes().then((rs) => setActiveResume(rs.find((r) => r.is_active) ?? null), () => setActiveResume(null));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const pickJob = (id: string) => {
    setJobId(id);
    const job = jobs?.find((j) => j.id === id);
    setSeniority(JOB_SENIORITY[job?.parsed?.seniority ?? ""] ?? defaultSeniority);
  };

  const job = jobs?.find((j) => j.id === jobId);
  const resume = activeResume ?? null;

  const start = async () => {
    setBusy(true);
    setError(null);
    try {
      const session = await api.createSession({
        type,
        job_posting_id: jobId || null,
        resume_id: resume?.id ?? null,
        seniority,
        interviewer_style: style,
        duration_min: duration,
        feedback_mode: feedback,
      });
      navigate(`/interviews/${session.id}`);
    } catch (err) {
      setError(errorText(err));
      setBusy(false);
    }
  };

  const typeLabel = TYPES.find((t) => t.value === type)!.label.toLowerCase();

  return (
    <section className="page wide">
      <header className="page-head">
        <h1>New interview</h1>
        <p className="lede">Choose what to practice. The interviewer speaks first as soon as you join.</p>
      </header>

      <div className="composer">
        <div className="composer-form">
          <section className="block" aria-labelledby="f-format">
            <h2 id="f-format">Format</h2>
            <div className="option-grid three" role="radiogroup" aria-labelledby="f-format">
              {TYPES.map((t) => (
                <button
                  key={t.value}
                  type="button"
                  role="radio"
                  aria-checked={type === t.value}
                  className={`option type-option type-${t.value}`}
                  onClick={() => setType(t.value)}
                >
                  <span className="option-title">
                    <span className={`type-mark type-${t.value}`} aria-hidden="true" />
                    {t.label}
                  </span>
                  <span className="option-hint">{t.hint}</span>
                  <span className="option-sample spoken">{t.sample}</span>
                </button>
              ))}
            </div>
          </section>

          <section className="block" aria-labelledby="f-context">
            <h2 id="f-context">Context</h2>
            <p className="soft block-note">A job posting sets the stack, seniority and domain. Your resume gives the interviewer real projects to ask about.</p>

            <h3 className="field-title">Job posting</h3>
            <div className="option-list" role="radiogroup" aria-label="Job posting">
              <button type="button" role="radio" aria-checked={jobId === ""} className="option row" onClick={() => pickJob("")}>
                <span className="option-title">General backend interview</span>
                <span className="option-hint">No specific job</span>
              </button>
              {jobs?.map((j) => (
                <button key={j.id} type="button" role="radio" aria-checked={jobId === j.id} className="option row" onClick={() => pickJob(j.id)}>
                  <span className="option-title">{j.title}</span>
                  <span className="option-hint">
                    {[j.company, j.parsed?.seniority !== "unknown" ? j.parsed?.seniority : null, j.parsed?.required_stack.slice(0, 3).join(", ")]
                      .filter(Boolean)
                      .join(" — ")}
                  </span>
                </button>
              ))}
              <Link to="/jobs" className="option row add">
                <Icon name="plus" size={16} /> Add a job posting
              </Link>
            </div>

            <h3 className="field-title">Resume</h3>
            {activeResume === undefined ? (
              <p className="soft">Loading…</p>
            ) : activeResume ? (
              <div className="resume-pick">
                <Icon name="resume" />
                <span>
                  <strong>{activeResume.parsed_profile?.name ?? activeResume.file_name}</strong>
                  <span className="soft small">
                    {activeResume.parsed_profile?.stack.slice(0, 5).join(", ") || activeResume.file_name}
                  </span>
                </span>
                <Link to="/profile" className="btn ghost small">Change</Link>
              </div>
            ) : (
              <p className="soft">
                No resume yet. <Link to="/profile">Upload one</Link> so behavioral questions use your real projects.
              </p>
            )}
          </section>

          <section className="block" aria-labelledby="f-interviewer">
            <h2 id="f-interviewer">Interviewer</h2>
            <div className="option-grid three" role="radiogroup" aria-labelledby="f-interviewer">
              {STYLES.map((s) => (
                <button key={s.value} type="button" role="radio" aria-checked={style === s.value} className="option" onClick={() => setStyle(s.value)}>
                  <span className="option-title">{s.label}</span>
                  <span className="option-hint">{s.hint}</span>
                </button>
              ))}
            </div>

            <div className="field-row">
              <div className="field">
                <span className="field-title">Seniority bar</span>
                <Segmented
                  label="Seniority"
                  value={seniority}
                  options={[{ value: "mid", label: "Mid-level" }, { value: "senior", label: "Senior" }]}
                  onChange={setSeniority}
                />
              </div>
              <div className="field">
                <span className="field-title">Length</span>
                <Segmented
                  label="Duration"
                  value={duration}
                  options={DURATIONS.map((d) => ({ value: d, label: `${d} min` }))}
                  onChange={setDuration}
                />
              </div>
            </div>

            <div className="field">
              <span className="field-title">Feedback</span>
              <Segmented label="Feedback" value={feedback} options={FEEDBACK} onChange={setFeedback} />
              <span className="soft small">{FEEDBACK.find((f) => f.value === feedback)?.hint}</span>
            </div>
          </section>
        </div>

        <aside className="composer-summary" aria-label="Summary">
          <h2>Your interview</h2>
          <p className="summary-sentence">
            A {duration}-minute {seniority === "senior" ? "senior" : "mid-level"} {typeLabel} interview with a{" "}
            {style} interviewer
            {job ? <>, tailored to <strong>{job.title}{job.company ? ` at ${job.company}` : ""}</strong></> : ", for a general backend role"}
            {resume ? <>, using your resume</> : null}. Feedback {feedback === "end" ? "at the end" : feedback === "live" ? "live, after each answer" : "live for serious mistakes, the rest at the end"}.
          </p>
          <p className="summary-tip">
            <Icon name="headphones" /> Wear headphones so the interviewer's voice does not leak into your microphone.
          </p>
          {error && <p className="notice error">{error}</p>}
          <button type="button" className="btn primary large" onClick={start} disabled={busy || jobs === null}>
            <Icon name="mic" /> {busy ? "Preparing…" : "Start interview"}
          </button>
        </aside>
      </div>
    </section>
  );
}
