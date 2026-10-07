/** Pick one of a few options (radiogroup semantics, arrow keys move the choice). */
export default function Segmented<T extends string | number>({
  value, options, onChange, label, size,
}: {
  value: T;
  options: { value: T; label: string }[];
  onChange: (v: T) => void;
  label: string;
  size?: "small";
}) {
  const move = (e: React.KeyboardEvent, i: number) => {
    const step = e.key === "ArrowRight" || e.key === "ArrowDown" ? 1 : e.key === "ArrowLeft" || e.key === "ArrowUp" ? -1 : 0;
    if (!step) return;
    e.preventDefault();
    const next = options[(i + step + options.length) % options.length];
    onChange(next.value);
    const group = e.currentTarget.parentElement;
    (group?.children[(i + step + options.length) % options.length] as HTMLElement | undefined)?.focus();
  };
  return (
    <div className={`segmented ${size ?? ""}`} role="radiogroup" aria-label={label}>
      {options.map((o, i) => (
        <button
          key={String(o.value)}
          type="button"
          role="radio"
          aria-checked={value === o.value}
          tabIndex={value === o.value ? 0 : -1}
          onClick={() => onChange(o.value)}
          onKeyDown={(e) => move(e, i)}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}
