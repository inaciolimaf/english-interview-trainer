"""Fluency metrics from Whisper word timestamps (section 10.1, step 1). Local, no LLM."""

import re

FILLERS = {"uh", "um", "uhm", "umm", "er", "erm", "ah", "hmm", "mm"}
FILLER_PHRASES = (("you", "know"), ("i", "mean"))
LONG_PAUSE_MS = 2000
_TOKEN = re.compile(r"[a-z']+")


def _norm(word: str) -> str:
    m = _TOKEN.findall(word.lower())
    return m[0] if m else ""


def fluency_metrics(words: list[dict]) -> dict:
    """WPM, long pauses (> 2 s between words) and filler counts for one answer."""
    if not words:
        return {"words": 0, "wpm": 0.0, "speaking_s": 0.0, "long_pauses": [], "fillers": {}, "filler_count": 0,
                "fillers_per_min": 0.0}
    tokens = [_norm(w["w"]) for w in words]
    fillers: dict[str, int] = {}
    for t in tokens:
        if t in FILLERS:
            fillers[t] = fillers.get(t, 0) + 1
    for a, b in FILLER_PHRASES:
        n = sum(1 for x, y in zip(tokens, tokens[1:]) if (x, y) == (a, b))
        if n:
            fillers[f"{a} {b}"] = n
    pauses = [
        {"after_word": i, "ms": nxt["start_ms"] - cur["end_ms"], "at_ms": cur["end_ms"]}
        for i, (cur, nxt) in enumerate(zip(words, words[1:]))
        if nxt["start_ms"] - cur["end_ms"] > LONG_PAUSE_MS
    ]
    speaking_s = max(0.001, (words[-1]["end_ms"] - words[0]["start_ms"]) / 1000)
    content_words = sum(1 for t in tokens if t and t not in FILLERS)
    filler_count = sum(fillers.values())
    return {
        "words": content_words,
        "wpm": round(content_words / (speaking_s / 60), 1),
        "speaking_s": round(speaking_s, 1),
        "long_pauses": pauses,
        "fillers": fillers,
        "filler_count": filler_count,
        "fillers_per_min": round(filler_count / (speaking_s / 60), 1),
    }


def fluency_errors(metrics: dict) -> list[dict]:
    """Turn-level fluency issues (no audio anchor, so no clip)."""
    out = []
    if metrics["filler_count"] >= 3 and metrics["fillers_per_min"] >= 4:
        top = ", ".join(f'"{k}" ×{v}' for k, v in sorted(metrics["fillers"].items(), key=lambda x: -x[1])[:3])
        out.append({
            "kind": "fluency", "category": "flu:filler",
            "severity": "high" if metrics["fillers_per_min"] >= 10 else "medium",
            "original_text": top,
            "explanation": (f"You used {metrics['filler_count']} fillers ({metrics['fillers_per_min']:.0f} per "
                            f"minute): {top}. Try a short silent pause instead, or a phrase like \"Let me think\"."),
        })
    pauses = metrics["long_pauses"]
    if pauses:
        longest = max(p["ms"] for p in pauses) / 1000
        out.append({
            "kind": "fluency", "category": "flu:long_pause",
            "severity": "medium" if len(pauses) >= 3 else "low",
            "original_text": f"{len(pauses)} pause(s) longer than 2 s (longest {longest:.1f} s)",
            "explanation": ("Long silences mid-answer can sound like you are stuck. Signal that you are thinking "
                            "(\"Let me think about that for a second\") or structure the answer before you start."),
        })
    return out
