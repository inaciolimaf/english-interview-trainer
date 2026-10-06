import { useEffect, useState } from "react";
import { api, type JobPosting } from "../api/client";
import Chips from "../components/Chips";

export default function Jobs() {
  const [jobs, setJobs] = useState<JobPosting[] | null>(null);
  const [text, setText] = useState("");
  const [title, setTitle] = useState("");
  const [company, setCompany] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);

  const load = () => api.listJobs().then(setJobs, (e) => setError(String(e)));
  useEffect(() => {
    load();
  }, []);

  const run = async (label: string, action: () => Promise<JobPosting | void>) => {
    setBusy(label);
    setError(null);
    try {
      const result = await action();
      if (result && result.parse_error) setError(`Saved, but the posting could not be analyzed: ${result.parse_error}`);
      await load();
      return true;
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e));
      return false;
    } finally {
      setBusy(null);
    }
  };

  const save = async () => {
    const ok = await run("save", () =>
      api.createJob({ raw_text: text, title: title || undefined, company: company || undefined }),
    );
    if (ok) {
      setText("");
      setTitle("");
      setCompany("");
    }
  };

  return (
    <section className="narrow-wide">
      <h2>Job postings</h2>
      <p className="muted">Paste a posting to tailor interviews: the stack, seniority and domain come from it.</p>

      <div className="card form">
        <div className="form-row">
          <label>
            Title <span className="muted small">(optional — extracted if empty)</span>
            <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Senior Backend Engineer" />
          </label>
          <label>
            Company <span className="muted small">(optional)</span>
            <input value={company} onChange={(e) => setCompany(e.target.value)} placeholder="Acme" />
          </label>
        </div>
        <label>
          Job description
          <textarea value={text} onChange={(e) => setText(e.target.value)} rows={8} placeholder="Paste the full job posting here…" />
        </label>
        <div>
          <button className="primary" onClick={save} disabled={busy !== null || text.trim().length < 50}>
            {busy === "save" ? "Saving and analyzing…" : "Save posting"}
          </button>
          {text.trim().length > 0 && text.trim().length < 50 && <span className="muted small"> Paste the full description.</span>}
        </div>
      </div>

      {error && <p className="error">{error}</p>}
      {jobs === null && <p className="muted">Loading…</p>}
      {jobs?.length === 0 && <p className="muted">No job postings yet.</p>}

      {jobs?.map((job) => (
        <article key={job.id} className="card">
          <header className="card-header">
            <div>
              <h3>{job.title}</h3>
              <span className="muted small">
                {[job.company, job.parsed?.domain, job.parsed && job.parsed.seniority !== "unknown" ? job.parsed.seniority : null]
                  .filter(Boolean)
                  .join(" · ")}
              </span>
            </div>
            <span className="row-actions">
              <button onClick={() => run(`reparse-${job.id}`, () => api.reparseJob(job.id))} disabled={busy !== null}>
                {busy === `reparse-${job.id}` ? "Re-parsing…" : "Re-parse"}
              </button>
              <button className="danger" onClick={() => run(`delete-${job.id}`, () => api.deleteJob(job.id))} disabled={busy !== null}>
                Delete
              </button>
            </span>
          </header>
          {job.parsed ? (
            <dl className="facts">
              {job.parsed.summary && (
                <>
                  <dt>Summary</dt>
                  <dd>{job.parsed.summary}</dd>
                </>
              )}
              <dt>Required</dt>
              <dd>
                <Chips items={job.parsed.required_stack} />
              </dd>
              <dt>Nice to have</dt>
              <dd>
                <Chips items={job.parsed.nice_to_have} />
              </dd>
            </dl>
          ) : (
            <p className="muted">Not analyzed — use Re-parse.</p>
          )}
          <button className="link" onClick={() => setOpen(open === job.id ? null : job.id)}>
            {open === job.id ? "Hide original text" : "Show original text"}
          </button>
          {open === job.id && <pre className="raw">{job.raw_text}</pre>}
        </article>
      ))}
    </section>
  );
}
