import { useEffect, useState } from "react";
import { api, type UserSettings } from "../api/client";

// American Kokoro voices (af_* female, am_* male)
const VOICES = [
  "af_heart", "af_bella", "af_nicole", "af_sarah", "af_sky", "af_nova", "af_river", "af_jessica",
  "am_michael", "am_adam", "am_eric", "am_liam", "am_echo", "am_onyx", "am_puck", "am_fenrir",
];

export default function Settings() {
  const [settings, setSettings] = useState<UserSettings | null>(null);
  const [draft, setDraft] = useState<UserSettings | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.getSettings().then((s) => {
      setSettings(s);
      setDraft(s);
    }, (e) => setError(String(e)));
  }, []);

  if (!draft || !settings) return <section><h2>Settings</h2>{error ? <p className="error">{error}</p> : <p className="muted">Loading…</p>}</section>;

  const set = <K extends keyof UserSettings>(key: K, value: UserSettings[K]) => {
    setDraft({ ...draft, [key]: value });
    setStatus(null);
  };
  const dirty = JSON.stringify(draft) !== JSON.stringify(settings);

  const save = async () => {
    setError(null);
    try {
      const saved = await api.patchSettings(draft);
      setSettings(saved);
      setDraft(saved);
      setStatus("Saved.");
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e));
    }
  };

  return (
    <section className="narrow-wide">
      <h2>Settings</h2>

      <fieldset>
        <legend>Interview defaults</legend>
        <div className="form-row">
          <label>
            Interviewer style
            <select value={draft.default_interviewer_style} onChange={(e) => set("default_interviewer_style", e.target.value as UserSettings["default_interviewer_style"])}>
              <option value="friendly">Friendly</option>
              <option value="neutral">Neutral</option>
              <option value="tough">Tough</option>
            </select>
          </label>
          <label>
            Seniority
            <select value={draft.default_seniority} onChange={(e) => set("default_seniority", e.target.value as UserSettings["default_seniority"])}>
              <option value="mid">Mid-level</option>
              <option value="senior">Senior</option>
            </select>
          </label>
          <label>
            Duration
            <select value={draft.default_duration_min} onChange={(e) => set("default_duration_min", Number(e.target.value) as UserSettings["default_duration_min"])}>
              {[15, 30, 45, 60].map((d) => (
                <option key={d} value={d}>
                  {d} minutes
                </option>
              ))}
            </select>
          </label>
          <label>
            Feedback
            <select value={draft.feedback_mode} onChange={(e) => set("feedback_mode", e.target.value as UserSettings["feedback_mode"])}>
              <option value="end">At the end</option>
              <option value="live">Live</option>
              <option value="hybrid">Hybrid</option>
            </select>
          </label>
        </div>
      </fieldset>

      <fieldset>
        <legend>Turn taking</legend>
        <div className="form-row">
          <label>
            Mode
            <select value={draft.turn_taking_mode} onChange={(e) => set("turn_taking_mode", e.target.value as UserSettings["turn_taking_mode"])}>
              <option value="auto">Hands-free (voice detection)</option>
              <option value="push_to_talk">Push-to-talk (hold Space)</option>
            </select>
          </label>
          <label>
            Silence before the interviewer answers: {(draft.end_of_turn_silence_ms / 1000).toFixed(1)} s
            <input
              type="range" min={800} max={3000} step={100} value={draft.end_of_turn_silence_ms}
              onChange={(e) => set("end_of_turn_silence_ms", Number(e.target.value))}
            />
            <span className="muted small">Used when the end-of-turn model is unsure. Longer = more time to think.</span>
          </label>
        </div>
      </fieldset>

      <fieldset>
        <legend>Interviewer voice</legend>
        <div className="form-row">
          <label>
            Voice
            <select value={draft.tts_voice} onChange={(e) => set("tts_voice", e.target.value)}>
              {VOICES.map((v) => (
                <option key={v} value={v}>
                  {v.replace("_", " · ")}
                </option>
              ))}
            </select>
          </label>
          <label>
            Speed: {draft.tts_speed.toFixed(2)}×
            <input type="range" min={0.7} max={1.3} step={0.05} value={draft.tts_speed} onChange={(e) => set("tts_speed", Number(e.target.value))} />
          </label>
        </div>
      </fieldset>

      <fieldset>
        <legend>Pronunciation analysis</legend>
        <label>
          Error threshold k: {draft.phoneme_threshold_k.toFixed(1)}
          <input type="range" min={1} max={3.5} step={0.1} value={draft.phoneme_threshold_k} onChange={(e) => set("phoneme_threshold_k", Number(e.target.value))} />
          <span className="muted small">Lower = stricter (more phoneme errors flagged). Used from the pronunciation feedback onwards.</span>
        </label>
      </fieldset>

      {error && <p className="error">{error}</p>}
      <div className="row-actions">
        <button className="primary" onClick={save} disabled={!dirty}>
          Save
        </button>
        <button onClick={() => setDraft(settings)} disabled={!dirty}>
          Discard changes
        </button>
        {status && <span className="muted">{status}</span>}
      </div>
    </section>
  );
}
