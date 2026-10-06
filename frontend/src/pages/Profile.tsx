import { useEffect, useRef, useState } from "react";
import { api, type ParsedProfile, type Resume } from "../api/client";
import Chips from "../components/Chips";

export default function Profile() {
  const [resumes, setResumes] = useState<Resume[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const load = () => api.listResumes().then(setResumes, (e) => setError(String(e)));
  useEffect(() => {
    load();
  }, []);

  const run = async (label: string, action: () => Promise<Resume | void>) => {
    setBusy(label);
    setError(null);
    try {
      const result = await action();
      if (result && result.parse_error) setError(`Saved, but the profile could not be extracted: ${result.parse_error}`);
      await load();
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e));
    } finally {
      setBusy(null);
    }
  };

  const upload = (file: File | undefined) => {
    if (file) void run("upload", () => api.uploadResume(file));
    if (fileRef.current) fileRef.current.value = "";
  };

  const active = resumes?.find((r) => r.is_active) ?? null;
  const others = resumes?.filter((r) => !r.is_active) ?? [];

  return (
    <section className="narrow-wide">
      <h2>Profile</h2>
      <p className="muted">
        Your resume personalizes the interviews: behavioral questions use your real projects, and technical questions
        use your stack when no job posting is selected.
      </p>

      <div className="card">
        <label className="upload">
          <input ref={fileRef} type="file" accept="application/pdf" onChange={(e) => upload(e.target.files?.[0])} disabled={busy !== null} />
          <span className="button primary">{busy === "upload" ? "Uploading and extracting…" : "Upload resume (PDF)"}</span>
        </label>
        <span className="muted small">Extraction uses the LLM and takes a few seconds.</span>
      </div>

      {error && <p className="error">{error}</p>}
      {resumes === null && <p className="muted">Loading…</p>}
      {resumes?.length === 0 && <p className="muted">No resume yet.</p>}

      {active && (
        <article className="card">
          <header className="card-header">
            <div>
              <h3>{active.parsed_profile?.name ?? active.file_name}</h3>
              <span className="muted small">Active resume · {active.file_name} · uploaded {new Date(active.created_at).toLocaleDateString()}</span>
            </div>
            <button onClick={() => run("reparse", () => api.reparseResume(active.id))} disabled={busy !== null}>
              {busy === "reparse" ? "Re-parsing…" : "Re-parse"}
            </button>
          </header>
          {active.parsed_profile ? (
            <ProfileView profile={active.parsed_profile} />
          ) : (
            <p className="muted">No extracted profile — use Re-parse.</p>
          )}
        </article>
      )}

      {others.length > 0 && (
        <>
          <h3>Other resumes</h3>
          <ul className="list">
            {others.map((r) => (
              <li key={r.id} className="list-row">
                <span>
                  {r.parsed_profile?.name ?? r.file_name}{" "}
                  <span className="muted small">{new Date(r.created_at).toLocaleDateString()}</span>
                </span>
                <span className="row-actions">
                  <button onClick={() => run("activate", () => api.activateResume(r.id))} disabled={busy !== null}>
                    Make active
                  </button>
                  <button className="danger" onClick={() => run("delete", () => api.deleteResume(r.id))} disabled={busy !== null}>
                    Delete
                  </button>
                </span>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}

function ProfileView({ profile }: { profile: ParsedProfile }) {
  return (
    <div className="profile">
      <dl className="facts">
        <dt>Experience</dt>
        <dd>{profile.years_of_experience != null ? `${profile.years_of_experience} years` : "—"}</dd>
        <dt>Stack</dt>
        <dd>
          <Chips items={profile.stack} />
        </dd>
      </dl>

      {profile.roles.length > 0 && (
        <>
          <h4>Roles</h4>
          <ul className="plain">
            {profile.roles.map((role, i) => (
              <li key={i}>
                <strong>{role.title}</strong>
                {role.company && <> · {role.company}</>}{" "}
                <span className="muted small">
                  {[role.start, role.end ?? "present"].filter(Boolean).join(" – ")}
                </span>
              </li>
            ))}
          </ul>
        </>
      )}

      {profile.projects.length > 0 && (
        <>
          <h4>Projects</h4>
          <ul className="plain">
            {profile.projects.map((p, i) => (
              <li key={i}>
                <strong>{p.name}</strong> — {p.description}
                {p.impact && <div className="muted small">Impact: {p.impact}</div>}
              </li>
            ))}
          </ul>
        </>
      )}

      {profile.achievements.length > 0 && (
        <>
          <h4>Achievements</h4>
          <ul className="plain">
            {profile.achievements.map((a, i) => (
              <li key={i}>{a}</li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
