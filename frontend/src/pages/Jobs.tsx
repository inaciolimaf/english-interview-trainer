import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type JobPosting } from "../api/client";
import Chips from "../components/Chips";
import ConfirmButton from "../components/ConfirmButton";
import { errorText } from "../components/format";
import Icon from "../components/Icon";

const MIN_CHARS = 50;

export default function Jobs() {
  const [jobs, setJobs] = useState<JobPosting[] | null>(null);
  const [text, setText] = useState("");
  const [title, setTitle] = useState("");
  const [company, setCompany] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [open, setOpen] = useState<string | null>(null);
  const [rawOpen, setRawOpen] = useState<string | null>(null);

  const load = () =>
    api.listJobs().then((js) => {
      setJobs(js);
      if (js.length === 0) setAdding(true);
    }, (e) => setError(errorText(e)));
  useEffect(() => {
    load();
  }, []);

  const run = async (label: string, action: () => Promise<JobPosting | void>) => {
    setBusy(label);
    setError(null);
    try {
      const result = await action();
      if (result && result.parse_error) setError(`Saved, but the posting could not be analyzed: ${result.parse_error}. Use Re-read to try again.`);
      await load();
      return result;
    } catch (e) {
      setError(errorText(e));
      return null;
    } finally {
      setBusy(null);
    }
  };

  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    const created = await run("save", () => api.createJob({ raw_text: text, title: title || undefined, company: company || undefined }));
    if (created) {
      setText("");
      setTitle("");
      setCompany("");
      setAdding(false);
      setOpen(created.id);
    }
  };

  const short = text.trim().length > 0 && text.trim().length < MIN_CHARS;

  return (
    <section className="page">
      <header className="page-head with-action">
        <div>
          <h1>Jobs</h1>
          <p className="lede">Paste a job posting to tailor interviews to it: the stack, seniority and domain come from the text.</p>
        </div>
        {!adding && (
          <button type="button" className="btn primary" onClick={() => setAdding(true)}>
            <Icon name="plus" size={16} /> Add a job
          </button>
        )}
      </header>

      {adding && (
        <form className="job-form" onSubmit={save}>
          <div className="field-row">
            <label className="field">
              <span className="field-title">Title <span className="soft">(optional, extracted if empty)</span></span>
              <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Senior Backend Engineer" />
            </label>
            <label className="field">
              <span className="field-title">Company <span className="soft">(optional)</span></span>
              <input value={company} onChange={(e) => setCompany(e.target.value)} placeholder="Acme" />
            </label>
          </div>
          <label className="field">
            <span className="field-title">Job description</span>
            <textarea value={text} onChange={(e) => setText(e.target.value)} rows={9} placeholder="Paste the whole posting: responsibilities, requirements, nice-to-haves…" />
            {short && <span className="soft small">That looks too short — paste the full description.</span>}
          </label>
          <div className="actions">
            <button type="submit" className="btn primary" disabled={busy !== null || text.trim().length < MIN_CHARS}>
              {busy === "save" ? "Saving and analyzing…" : "Save job"}
            </button>
            {(jobs?.length ?? 0) > 0 && (
              <button type="button" className="btn ghost" onClick={() => setAdding(false)}>Cancel</button>
            )}
          </div>
        </form>
      )}

      {error && <p className="notice error">{error}</p>}
      {jobs === null && !error && <p className="soft">Loading…</p>}

      <ul className="job-list">
        {jobs?.map((job) => {
          const expanded = open === job.id;
          const p = job.parsed;
          return (
            <li key={job.id} className={`job ${expanded ? "open" : ""}`}>
              <button type="button" className="job-summary" onClick={() => setOpen(expanded ? null : job.id)} aria-expanded={expanded}>
                <span className="job-title">
                  <strong>{job.title}</strong>
                  <span className="soft small">
                    {[job.company, p?.domain, p && p.seniority !== "unknown" ? p.seniority : null].filter(Boolean).join(", ") || "No details extracted"}
                  </span>
                </span>
                <span className="job-stack">{p?.required_stack.slice(0, 4).join(" · ")}</span>
                <Icon name="chevron" size={16} />
              </button>
              {expanded && (
                <div className="job-detail">
                  {p ? (
                    <>
                      {p.summary && <p className="reading">{p.summary}</p>}
                      <div className="field-row">
                        <section>
                          <h3>Required</h3>
                          <Chips items={p.required_stack} />
                        </section>
                        <section>
                          <h3>Nice to have</h3>
                          <Chips items={p.nice_to_have} tone="quiet" />
                        </section>
                      </div>
                      {p.responsibilities.length > 0 && (
                        <section>
                          <h3>Responsibilities</h3>
                          <ul className="bullets">
                            {p.responsibilities.map((r, i) => <li key={i}>{r}</li>)}
                          </ul>
                        </section>
                      )}
                    </>
                  ) : (
                    <p className="soft">This posting was not analyzed. Use Re-read to try again.</p>
                  )}
                  <button type="button" className="btn ghost small" onClick={() => setRawOpen(rawOpen === job.id ? null : job.id)} aria-expanded={rawOpen === job.id}>
                    {rawOpen === job.id ? "Hide the original text" : "Show the original text"}
                  </button>
                  {rawOpen === job.id && <pre className="raw">{job.raw_text}</pre>}
                  <footer className="actions">
                    <Link to={`/interviews/new?job=${job.id}`} className="btn primary">
                      <Icon name="mic" size={16} /> Practice for this job
                    </Link>
                    <button type="button" className="btn ghost" onClick={() => run(`reparse-${job.id}`, () => api.reparseJob(job.id))} disabled={busy !== null}>
                      <Icon name="refresh" size={14} /> {busy === `reparse-${job.id}` ? "Re-reading…" : "Re-read"}
                    </button>
                    <ConfirmButton className="btn ghost danger" confirm="Delete this job?" onConfirm={() => run(`delete-${job.id}`, () => api.deleteJob(job.id))} disabled={busy !== null}>
                      <Icon name="trash" size={14} /> Delete
                    </ConfirmButton>
                  </footer>
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
