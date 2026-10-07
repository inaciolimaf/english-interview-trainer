import { useState } from "react";
import { api } from "../api/client";
import type { LiveFeedbackItem } from "../realtime/protocol";
import { KIND_LABEL } from "./ErrorCard";
import Icon from "./Icon";

/** Text-only notes on the last analyzed answer (section 10.2): silent, never interrupts. */
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
    <aside className="live-feedback" aria-label="Notes on your last answer" aria-live="polite">
      <header>
        <h3>On your last answer</h3>
        <button type="button" className="icon-btn" onClick={onClose} aria-label="Hide notes">
          <Icon name="close" size={16} />
        </button>
      </header>
      {visible.map((item) => (
        <div key={item.error_id} className={`fb-note sev-${item.severity}`}>
          <span className="fb-kind">
            <span className={`kind-dot kind-${item.kind}`} />
            {KIND_LABEL[item.kind]}
            {item.word && <> · <span className="spoken">{item.word}</span></>}
          </span>
          {item.kind !== "pronunciation" && item.original_text && (
            <div className="said compact">
              <p className="said-wrong">{item.original_text}</p>
              {item.corrected_text && <p className="said-right">{item.corrected_text}</p>}
            </div>
          )}
          {item.explanation && <p>{item.explanation}</p>}
          {item.kind === "pronunciation" && (
            <button type="button" className="btn ghost small" onClick={() => notAnError(item.error_id)}>
              Not an error
            </button>
          )}
        </div>
      ))}
    </aside>
  );
}
