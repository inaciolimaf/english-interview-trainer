import { useEffect, useState } from "react";
import { api, type Health } from "../api/client";

/** Three dots in the rail footer (API, database, model server); details on demand. */
export default function SystemStatus() {
  const [health, setHealth] = useState<Health | null>(null);
  const [apiError, setApiError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      try {
        const h = await api.health();
        if (!cancelled) {
          setHealth(h);
          setApiError(null);
        }
      } catch (err) {
        if (!cancelled) setApiError(String(err instanceof Error ? err.message : err));
      }
    };
    void poll();
    const id = setInterval(poll, 5000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  const rows = [
    { label: "API", ok: apiError ? false : health?.api.ok, error: apiError ?? health?.api.error },
    { label: "Database", ok: apiError ? false : health?.database.ok, error: health?.database.error },
    { label: "Model server", ok: apiError ? false : health?.model_server.ok, error: health?.model_server.error },
  ];
  const down = rows.filter((r) => r.ok === false);
  const summary = !health && !apiError ? "Checking services…" : down.length === 0 ? "All services running" : `${down.map((r) => r.label).join(", ")} offline`;

  return (
    <div className={`system-status ${down.length ? "has-problem" : ""}`}>
      <button type="button" className="status-toggle" onClick={() => setOpen(!open)} aria-expanded={open}>
        <span className="dots">
          {rows.map((r) => (
            <i key={r.label} className={r.ok === undefined ? "" : r.ok ? "ok" : "down"} />
          ))}
        </span>
        <span>{summary}</span>
      </button>
      {open && (
        <ul>
          {rows.map((r) => (
            <li key={r.label}>
              <i className={r.ok === undefined ? "" : r.ok ? "ok" : "down"} />
              <span>
                {r.label}
                {r.ok === false && r.error && <small>{r.error}</small>}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
