import { useState } from "react";
import { api, type ErrorItem } from "../api/client";
import { playClip } from "./clip";
import Icon from "./Icon";
import Phoneme from "./Phoneme";

export const KIND_LABEL: Record<ErrorItem["kind"], string> = {
  pronunciation: "Pronunciation",
  grammar: "Grammar",
  technical: "Technical",
  fluency: "Fluency",
  vocabulary: "Vocabulary",
};

export const KIND_ORDER: ErrorItem["kind"][] = ["pronunciation", "grammar", "vocabulary", "technical", "fluency"];

/** "pron:phoneme:θ" → "phoneme θ", "gram:verb_tense" → "verb tense". */
export function categoryLabel(category: string): string {
  if (category === "pron:suspect") return "unclear word";
  const [, ...rest] = category.split(":");
  return rest.join(" ").replaceAll("_", " ");
}

/** The IPA symbol inside a phoneme category, if any ("pron:phoneme:θ" → "θ"). */
export function categoryPhoneme(category: string): string | null {
  const m = category.match(/^pron:(?:phoneme|vowel):(.+)$/);
  return m ? m[1] : null;
}

const SEVERITY: Record<ErrorItem["severity"], string> = { high: "High impact", medium: "Medium", low: "Minor" };

/** One error: what you said → what to say, why, your clip and "Not an error". */
export default function ErrorCard({ error, onChange, showKind = true }: { error: ErrorItem; onChange?: (e: ErrorItem) => void; showKind?: boolean }) {
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

  const phoneme = categoryPhoneme(item.category);

  return (
    <article className={`error-card sev-${item.severity} ${item.dismissed ? "dismissed" : ""}`}>
      <header>
        {/* inside a category group the header already names it */}
        {showKind ? (
          <span className="error-cat">
            <span className={`kind-dot kind-${item.kind}`} />
            {KIND_LABEL[item.kind]} · {phoneme ? <>sound <Phoneme ipa={phoneme} /></> : categoryLabel(item.category)}
          </span>
        ) : (
          <span />
        )}
        <span className={`sev sev-${item.severity}`}>{SEVERITY[item.severity]}</span>
      </header>

      {item.kind === "pronunciation" ? (
        item.word && (
          <div className="said said-pron">
            <span className="said-word">{item.word}</span>
            {item.expected_phonemes && (
              <span className="said-ipa">
                <span>
                  <small>expected</small> <Phoneme ipa={item.expected_phonemes} />
                </span>
                {item.heard_phonemes && (
                  <span className="heard">
                    <small>heard</small> <Phoneme ipa={item.heard_phonemes} />
                  </span>
                )}
              </span>
            )}
          </div>
        )
      ) : (
        item.original_text && (
          <div className="said">
            <p className="said-wrong">{item.original_text}</p>
            {item.corrected_text && <p className="said-right">{item.corrected_text}</p>}
          </div>
        )
      )}

      {item.explanation && <p className="error-why">{item.explanation}</p>}

      <footer>
        {item.audio_url && (
          <button type="button" className="btn small" onClick={() => playClip(item.audio_url!)}>
            <Icon name="play" size={14} /> Your recording
          </button>
        )}
        {item.kind === "pronunciation" && item.category !== "pron:suspect" && !item.dismissed && (
          <button type="button" className="btn ghost small" onClick={dismiss} disabled={busy}>
            Not an error
          </button>
        )}
        {item.dismissed && <span className="soft small">Marked as not an error</span>}
        <span className="soft small error-date">{new Date(item.created_at).toLocaleDateString("en-US")}</span>
      </footer>
    </article>
  );
}
