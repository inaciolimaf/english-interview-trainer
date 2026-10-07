import { useEffect, useState, type ReactNode } from "react";

/** A destructive action that asks once, in place (no browser dialog). */
export default function ConfirmButton({
  children, confirm, onConfirm, disabled, className = "btn danger",
}: {
  children: ReactNode;
  confirm: string;
  onConfirm: () => void;
  disabled?: boolean;
  className?: string;
}) {
  const [asking, setAsking] = useState(false);
  useEffect(() => {
    if (!asking) return;
    const id = window.setTimeout(() => setAsking(false), 6000);
    return () => window.clearTimeout(id);
  }, [asking]);
  if (!asking) {
    return (
      <button type="button" className={className} onClick={() => setAsking(true)} disabled={disabled}>
        {children}
      </button>
    );
  }
  return (
    <span className="confirm" role="group" aria-label={confirm}>
      <span className="soft small">{confirm}</span>
      <button type="button" className="btn danger solid" onClick={() => { setAsking(false); onConfirm(); }} autoFocus>
        Yes
      </button>
      <button type="button" className="btn ghost" onClick={() => setAsking(false)}>
        Cancel
      </button>
    </span>
  );
}
