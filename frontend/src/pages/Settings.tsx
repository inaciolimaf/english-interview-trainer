import { useEffect, useState } from "react";
import { api, type UserSettings } from "../api/client";
import { errorText } from "../components/format";
import Icon from "../components/Icon";
import Segmented from "../components/Segmented";
import { speak, stopSpeaking } from "../components/speech";

// American Kokoro voices (af_* female, am_* male)
const VOICES = [
  "af_heart", "af_bella", "af_nicole", "af_sarah", "af_sky", "af_nova", "af_river", "af_jessica",
  "am_michael", "am_adam", "am_eric", "am_liam", "am_echo", "am_onyx", "am_puck", "am_fenrir",
];
const PREVIEW = "Thanks for joining. Let's start with your most recent project — what problem were you solving?";

function voiceName(v: string): string {
  const name = v.split("_")[1] ?? v;
  return name.charAt(0).toUpperCase() + name.slice(1);
}

export default function Settings() {
  const [settings, setSettings] = useState<UserSettings | null>(null);
  const [draft, setDraft] = useState<UserSettings | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [previewing, setPreviewing] = useState(false);

  useEffect(() => {
    api.getSettings().then((s) => {
      setSettings(s);
      setDraft(s);
    }, (e) => setError(errorText(e)));
    return () => stopSpeaking();
  }, []);

  if (!draft || !settings) {
    return (
      <section className="page narrow">
        <header className="page-head"><h1>Settings</h1></header>
        {error ? <p className="notice error">Could not load your settings: {error}</p> : <p className="soft">Loading…</p>}
      </section>
    );
  }

  const set = <K extends keyof UserSettings>(key: K, value: UserSettings[K]) => {
    setDraft({ ...draft, [key]: value });
    setStatus(null);
  };
  const dirty = JSON.stringify(draft) !== JSON.stringify(settings);

  const save = async () => {
    setError(null);
    setSaving(true);
    try {
      const saved = await api.patchSettings(draft);
      setSettings(saved);
      setDraft(saved);
      setStatus("Settings saved.");
    } catch (e) {
      setError(errorText(e));
    } finally {
      setSaving(false);
    }
  };

  const preview = async () => {
    setPreviewing(true);
    setError(null);
    try {
      await speak(PREVIEW, { voice: draft.tts_voice, speed: draft.tts_speed });
    } catch (e) {
      setError(`Could not play the preview: ${errorText(e)}`);
    } finally {
      setPreviewing(false);
    }
  };

  const female = VOICES.filter((v) => v.startsWith("af_"));
  const male = VOICES.filter((v) => v.startsWith("am_"));

  return (
    <section className="page settings">
      <header className="page-head">
        <h1>Settings</h1>
        <p className="lede">Defaults for new interviews, how turns work, and how strict the pronunciation check is.</p>
      </header>

      <section className="setting-group">
        <div className="setting-intro">
          <h2>Interview defaults</h2>
          <p className="soft">Preselected on the New interview page. You can still change them for each interview.</p>
        </div>
        <div className="setting-controls">
          <div className="field">
            <span className="field-title">Interviewer</span>
            <Segmented
              label="Interviewer style"
              value={draft.default_interviewer_style}
              onChange={(v) => set("default_interviewer_style", v)}
              options={[{ value: "friendly", label: "Friendly" }, { value: "neutral", label: "Neutral" }, { value: "tough", label: "Tough" }]}
            />
          </div>
          <div className="field">
            <span className="field-title">Seniority bar</span>
            <Segmented
              label="Seniority"
              value={draft.default_seniority}
              onChange={(v) => set("default_seniority", v)}
              options={[{ value: "mid", label: "Mid-level" }, { value: "senior", label: "Senior" }]}
            />
          </div>
          <div className="field">
            <span className="field-title">Length</span>
            <Segmented
              label="Duration"
              value={draft.default_duration_min}
              onChange={(v) => set("default_duration_min", v)}
              options={([15, 30, 45, 60] as const).map((d) => ({ value: d, label: `${d} min` }))}
            />
          </div>
          <div className="field">
            <span className="field-title">Feedback</span>
            <Segmented
              label="Feedback"
              value={draft.feedback_mode}
              onChange={(v) => set("feedback_mode", v)}
              options={[{ value: "end", label: "At the end" }, { value: "live", label: "Live" }, { value: "hybrid", label: "Hybrid" }]}
            />
          </div>
        </div>
      </section>

      <section className="setting-group">
        <div className="setting-intro">
          <h2>Turn taking</h2>
          <p className="soft">Hands-free detects when you finish talking. Push-to-talk sends only while you hold Space.</p>
        </div>
        <div className="setting-controls">
          <div className="field">
            <span className="field-title">Mode</span>
            <Segmented
              label="Turn taking mode"
              value={draft.turn_taking_mode}
              onChange={(v) => set("turn_taking_mode", v)}
              options={[{ value: "auto", label: "Hands-free" }, { value: "push_to_talk", label: "Push-to-talk" }]}
            />
          </div>
          <label className="field">
            <span className="field-title">
              Thinking time <output>{(draft.end_of_turn_silence_ms / 1000).toFixed(1)} s</output>
            </span>
            <input
              type="range" min={800} max={3000} step={100} value={draft.end_of_turn_silence_ms}
              onChange={(e) => set("end_of_turn_silence_ms", Number(e.target.value))}
            />
            <span className="soft small">How long you can stay silent before the interviewer answers, when the end-of-turn model is unsure. Longer gives you more time to think.</span>
          </label>
        </div>
      </section>

      <section className="setting-group">
        <div className="setting-intro">
          <h2>Interviewer voice</h2>
          <p className="soft">American English voices. The same voice reads the coach's replies.</p>
        </div>
        <div className="setting-controls">
          {[{ label: "Female", list: female }, { label: "Male", list: male }].map((g) => (
            <div key={g.label} className="field">
              <span className="field-title">{g.label}</span>
              <div className="voice-grid" role="radiogroup" aria-label={`${g.label} voices`}>
                {g.list.map((v) => (
                  <button key={v} type="button" role="radio" aria-checked={draft.tts_voice === v} className="chip-btn" onClick={() => set("tts_voice", v)}>
                    {voiceName(v)}
                  </button>
                ))}
              </div>
            </div>
          ))}
          <label className="field">
            <span className="field-title">
              Speed <output>{draft.tts_speed.toFixed(2)}×</output>
            </span>
            <input type="range" min={0.7} max={1.3} step={0.05} value={draft.tts_speed} onChange={(e) => set("tts_speed", Number(e.target.value))} />
          </label>
          <div>
            <button type="button" className="btn" onClick={previewing ? () => { stopSpeaking(); setPreviewing(false); } : preview}>
              <Icon name={previewing ? "stop" : "speaker"} size={16} /> {previewing ? "Stop preview" : `Hear ${voiceName(draft.tts_voice)}`}
            </button>
          </div>
        </div>
      </section>

      <section className="setting-group">
        <div className="setting-intro">
          <h2>Pronunciation check</h2>
          <p className="soft">How far a sound must be from native speakers before it counts as an error.</p>
        </div>
        <div className="setting-controls">
          <label className="field">
            <span className="field-title">
              Strictness <output>k = {draft.phoneme_threshold_k.toFixed(1)}</output>
            </span>
            <input
              type="range" min={1} max={3.5} step={0.1} value={draft.phoneme_threshold_k}
              onChange={(e) => set("phoneme_threshold_k", Number(e.target.value))}
            />
            <span className="range-ends small soft"><span>Stricter, more errors</span><span>More lenient</span></span>
            <span className="soft small">Applies to answers analyzed after you save.</span>
          </label>
        </div>
      </section>

      {error && <p className="notice error">{error}</p>}

      <div className={`save-bar ${dirty ? "show" : ""}`} aria-live="polite">
        <span>{dirty ? "You have unsaved changes." : status ?? "All changes saved."}</span>
        <button type="button" className="btn ghost" onClick={() => setDraft(settings)} disabled={!dirty || saving}>
          Discard
        </button>
        <button type="button" className="btn primary" onClick={save} disabled={!dirty || saving}>
          {saving ? "Saving…" : "Save changes"}
        </button>
      </div>
    </section>
  );
}
