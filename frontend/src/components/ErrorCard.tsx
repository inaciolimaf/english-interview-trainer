import { useState } from "react";
import { api, type ErrorItem } from "../api/client";
import { playClip } from "./clip";

export const KIND_LABEL: Record<ErrorItem["kind"], string> = {
  pronunciation: "Pronunciation",
  grammar: "Grammar",
  technical: "Technical",
  fluency: "Fluency",
  vocabulary: "Vocabulary",
};

export function categoryLabel(category: string): string {
  if (category === "pron:suspect") return "unclear word";
  const [, ...rest] = category.split(":");
  return rest.join(" ").replaceAll("_", " ");
}

/** One error: original → corrected, explanation, clip and "Not an error". */
export default function ErrorCard({ error, onChange }: { error: ErrorItem; onChange?: (e: ErrorItem) => void }) {
  const [item, setItem] = useState(error);
  const [busy, setBusy] = useState(false);

  const dismiss = async () => {
    setBusy(true);
    try {
      const updated = await api.dismissError(item.id);
      setItem(updated);
      onChange?.(updated);
    } finally {
      setBusy(false);
    }
  };

  return (
    <article className={`error-card sev-${item.severity} ${item.dismissed ? "dismissed" : ""}`}>
      <header>
        <span className="fb-kind">
          {KIND_LABEL[item.kind]} · {categoryLabel(item.category)}
        </span>
        <span className={`sev-tag sev-${item.severity}`}>{item.severity}</span>
      </header>
      {item.kind === "pronunciation" ? (
        item.word && (
          <p className="fb-diff">
            <strong>{item.word}</strong>
            {item.expected_phonemes && (
              <span className="muted small">
                {" "}
                expected /{item.expected_phonemes}/{item.heard_phonemes ? ` · heard /${item.heard_phonemes}/` : ""}
              </span>
            )}
          </p>
        )
      ) : (
        item.original_text && (
          <p className="fb-diff">
            <s>{item.original_text}</s>
            {item.corrected_text && (
              <>
                {" "}→ <strong>{item.corrected_text}</strong>
              </>
            )}
          </p>
        )
      )}
      {item.explanation && <p>{item.explanation}</p>}
      <div className="row-actions">
        {item.audio_url && (
          <button className="small" onClick={() => playClip(item.audio_url!)} aria-label="Play the clip of this error">
            ▶ Play clip
          </button>
        )}
        {item.kind === "pronunciation" && item.category !== "pron:suspect" && !item.dismissed && (
          <button className="link small" onClick={dismiss} disabled={busy}>
            Not an error
          </button>
        )}
        {item.dismissed && <span className="muted small">Marked as not an error</span>}
      </div>
    </article>
  );
}
