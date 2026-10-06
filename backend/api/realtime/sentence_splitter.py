"""Accumulates streamed LLM tokens and releases complete sentences for TTS (section 7.3)."""

import re

# Lower-cased tokens that end with "." but don't end a sentence
ABBREVIATIONS = {
    "e.g.", "i.e.", "etc.", "vs.", "mr.", "mrs.", "ms.", "dr.", "prof.", "sr.", "jr.",
    "approx.", "dept.", "inc.", "ltd.", "co.", "corp.", "st.", "no.", "fig.", "cf.", "u.s.",
}
_BOUNDARY = re.compile(r"[.!?…]+[\"')\]]*(?=\s)")
MIN_CHARS = 12  # shorter "sentences" ("Okay.") are merged into the next one


class SentenceSplitter:
    def __init__(self, min_chars: int = MIN_CHARS) -> None:
        self.buffer = ""
        self.min_chars = min_chars

    def feed(self, token: str) -> list[str]:
        self.buffer += token
        out: list[str] = []
        search_from = 0
        while m := _BOUNDARY.search(self.buffer, search_from):
            end = m.end()
            candidate = self.buffer[:end].strip()
            if self._is_false_boundary(self.buffer, m.start(), end) or len(candidate) < self.min_chars:
                search_from = end
                continue
            out.append(candidate)
            self.buffer = self.buffer[end:].lstrip()
            search_from = 0
        return out

    def flush(self) -> list[str]:
        rest, self.buffer = self.buffer.strip(), ""
        return [rest] if rest else []

    @staticmethod
    def _is_false_boundary(text: str, start: int, end: int) -> bool:
        if text[start] != ".":
            return False
        word = text[:end].split()[-1].lower() if text[:end].split() else ""
        word = word.rstrip("\"')]")
        if word in ABBREVIATIONS:
            return True
        # decimals / versions ("3.5", "v1.2") never reach here since we require whitespace
        # after the dot; single capital initials ("J. Smith") are not boundaries
        return bool(re.fullmatch(r"[a-z]\.", word))
