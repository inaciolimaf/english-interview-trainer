import { useState } from "react";
import { api } from "../api/client";
import type { LiveFeedbackItem } from "../realtime/protocol";

const KIND_LABEL: Record<LiveFeedbackItem["kind"], string> = {
  pronunciation: "Pronunciation",
  grammar: "Grammar",
  technical: "Technical",
  fluency: "Fluency",
  vocabulary: "Vocabulary",
};

/** Text-only cards for the last analyzed answer (section 10.2): silent, never interrupts. */
export default function LiveFeedback({ items, onClose }: { items: LiveFeedbackItem[]; onClose: () => void }) {
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());
  const visible = items.filter((i) => !dismissed.has(i.error_id));
  if (visible.length === 0) return null;

  const notAnError = async (id: string) => {
    setDismissed((d) => new Set(d).add(id));
    try {
      await api.dismissError(id);
    } catch {
      setDismissed((d) => {
        const next = new Set(d);
        next.delete(id);
        return next;
      });
    }
  };

  return (
    <aside className="live-feedback" aria-label="Feedback on your last answer" aria-live="polite">
      <header>
        <span className="small muted">Last answer</span>
        <button className="link" onClick={onClose} aria-label="Hide feedback">
          Hide
        </button>
      </header>
      {visible.map((item) => (
        <div key={item.error_id} className={`fb-card sev-${item.severity}`}>
          <span className="fb-kind">{KIND_LABEL[item.kind]}</span>
          {item.kind !== "pronunciation" && item.original_text && (
            <p className="fb-diff">
              <s>{item.original_text}</s>
              {item.corrected_text && <> → <strong>{item.corrected_text}</strong></>}
            </p>
          )}
          <p>{item.explanation}</p>
          {item.kind === "pronunciation" && (
            <button className="link small" onClick={() => notAnError(item.error_id)}>
              Not an error
            </button>
          )}
        </div>
      ))}
    </aside>
  );
}
