/** Overall rubric average (1–5) on a half dial. */
export default function ScoreDial({ score }: { score: number | null | undefined }) {
  const r = 52;
  const len = Math.PI * r;
  const t = score == null ? 0 : Math.max(0, Math.min(1, (score - 1) / 4));
  return (
    <figure className="score-dial" aria-label={score == null ? "No overall score" : `Overall ${score.toFixed(1)} out of 5`}>
      <svg viewBox="0 0 128 74" aria-hidden="true">
        <path d="M12 66a52 52 0 0 1 104 0" className="dial-track" />
        <path d="M12 66a52 52 0 0 1 104 0" className="dial-value" strokeDasharray={`${len * t} ${len}`} />
      </svg>
      <figcaption>
        <strong>{score == null ? "—" : score.toFixed(1)}</strong>
        <span>of 5</span>
      </figcaption>
    </figure>
  );
}
