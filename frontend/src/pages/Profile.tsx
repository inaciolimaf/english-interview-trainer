import { useEffect, useRef, useState } from "react";
import { api, type ParsedProfile, type Resume } from "../api/client";
import Chips from "../components/Chips";
import ConfirmButton from "../components/ConfirmButton";
import { errorText } from "../components/format";
import Icon from "../components/Icon";

export default function Profile() {
  const [resumes, setResumes] = useState<Resume[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const load = () => api.listResumes().then(setResumes, (e) => setError(errorText(e)));
  useEffect(() => {
    load();
  }, []);

  const run = async (label: string, action: () => Promise<Resume | void>) => {
    setBusy(label);
    setError(null);
    try {
      const result = await action();
      if (result && result.parse_error) setError(`Saved, but the profile could not be extracted: ${result.parse_error}. Use Re-read to try again.`);
      await load();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(null);
    }
  };

  const upload = (file: File | undefined) => {
    if (file && file.type !== "application/pdf" && !file.name.toLowerCase().endsWith(".pdf")) {
      setError("Only PDF files can be read. Export your resume as PDF and drop it again.");
    } else if (file) {
      void run("upload", () => api.uploadResume(file));
    }
    if (fileRef.current) fileRef.current.value = "";
  };

  const active = resumes?.find((r) => r.is_active) ?? null;
  const others = resumes?.filter((r) => !r.is_active) ?? [];

  return (
    <section className="page">
      <header className="page-head">
        <h1>Resume</h1>
        <p className="lede">
          Your resume personalizes the interviews: behavioral questions use your real projects, and technical questions use
          your stack when no job posting is selected.
        </p>
      </header>

      <label
        className={`dropzone ${dragging ? "dragging" : ""} ${busy === "upload" ? "busy" : ""}`}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          upload(e.dataTransfer.files[0]);
        }}
      >
        <input ref={fileRef} type="file" accept="application/pdf" onChange={(e) => upload(e.target.files?.[0])} disabled={busy !== null} />
        <Icon name="upload" size={26} />
        <span className="dropzone-title">{busy === "upload" ? "Reading your resume…" : active ? "Upload a newer resume" : "Upload your resume"}</span>
        <span className="soft small">
          {busy === "upload" ? "Extracting roles, projects and stack takes a few seconds." : "Drop a PDF here or click to choose one. The newest upload becomes active."}
        </span>
      </label>

      {error && <p className="notice error">{error}</p>}
      {resumes === null && !error && <p className="soft">Loading…</p>}

      {active && (
        <article className="resume-sheet">
          <header>
            <div>
              <span className="tag live">Active</span>
              <h2>{active.parsed_profile?.name ?? active.file_name}</h2>
              <p className="soft small">
                {active.file_name}, uploaded {new Date(active.created_at).toLocaleDateString("en-US")}
                {active.parsed_profile?.years_of_experience != null && ` · ${active.parsed_profile.years_of_experience} years of experience`}
              </p>
            </div>
            <button type="button" className="btn ghost small" onClick={() => run("reparse", () => api.reparseResume(active.id))} disabled={busy !== null}>
              <Icon name="refresh" size={14} /> {busy === "reparse" ? "Re-reading…" : "Re-read"}
            </button>
          </header>
          {active.parsed_profile ? (
            <ProfileView profile={active.parsed_profile} />
          ) : (
            <p className="soft">Nothing could be extracted from this file. Use Re-read, or upload a text-based PDF (not a scan).</p>
          )}
        </article>
      )}

      {others.length > 0 && (
        <section className="block">
          <h2>Earlier resumes</h2>
          <ul className="plain-rows">
            {others.map((r) => (
              <li key={r.id}>
                <span>
                  <strong>{r.parsed_profile?.name ?? r.file_name}</strong>
                  <span className="soft small">{r.file_name}, {new Date(r.created_at).toLocaleDateString("en-US")}</span>
                </span>
                <span className="actions">
                  <button type="button" className="btn small" onClick={() => run("activate", () => api.activateResume(r.id))} disabled={busy !== null}>
                    Make active
                  </button>
                  <ConfirmButton className="btn ghost small danger" confirm="Delete this resume?" onConfirm={() => run("delete", () => api.deleteResume(r.id))} disabled={busy !== null}>
                    <Icon name="trash" size={14} /> Delete
                  </ConfirmButton>
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </section>
  );
}

function ProfileView({ profile }: { profile: ParsedProfile }) {
  return (
    <div className="resume-body">
      <section>
        <h3>Stack</h3>
        <Chips items={profile.stack} />
      </section>

      {profile.roles.length > 0 && (
        <section>
          <h3>Roles</h3>
          <ol className="timeline">
            {profile.roles.map((role, i) => (
              <li key={i}>
                <span className="when">{[role.start, role.end ?? "present"].filter(Boolean).join(" – ")}</span>
                <div>
                  <strong>{role.title}</strong>
                  {role.company && <span className="soft"> at {role.company}</span>}
                  {role.highlights.length > 0 && (
                    <ul>
                      {role.highlights.map((h, j) => <li key={j}>{h}</li>)}
                    </ul>
                  )}
                </div>
              </li>
            ))}
          </ol>
        </section>
      )}

      {profile.projects.length > 0 && (
        <section>
          <h3>Projects the interviewer can ask about</h3>
          <ul className="projects">
            {profile.projects.map((p, i) => (
              <li key={i}>
                <strong>{p.name}</strong>
                <p>{p.description}</p>
                {p.impact && <p className="impact">{p.impact}</p>}
                {p.stack.length > 0 && <Chips items={p.stack} tone="quiet" />}
              </li>
            ))}
          </ul>
        </section>
      )}

      {profile.achievements.length > 0 && (
        <section>
          <h3>Achievements</h3>
          <ul className="marks good">
            {profile.achievements.map((a, i) => (
              <li key={i}><Icon name="check" size={16} />{a}</li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
