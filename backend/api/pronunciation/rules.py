"""Phoneme error decision (sections 8.1 step 7, 8.4, 8.5). Pure functions — no I/O.

A phone is an error candidate when its GOP score is below the native distribution:
    score < native_mean - k * native_std - user_offset
(stricter k for technical vocabulary), and what was heard is not an accepted variant.
"""

from dataclasses import dataclass, field

from api.pronunciation.align import Edit, align, distance

VOWELS = {
    "i", "iː", "ɪ", "eɪ", "ɛ", "æ", "ɑː", "ɑ", "ɔː", "ɔ", "oʊ", "ʊ", "uː", "u", "ʌ", "ə", "ɚ",
    "ɜː", "aɪ", "aʊ", "ɔɪ", "ɐ", "ᵻ", "e", "o", "a", "iə", "aɪə", "aɪɚ",
}
EPENTHETIC = {"i", "ɪ", "e", "ɛ", "ə", "ɐ", "iː", "ᵻ"}
# Function words: weak forms vary a lot in connected speech and errors there rarely matter
FUNCTION_WORDS = {
    "a", "an", "the", "to", "of", "and", "or", "for", "at", "in", "on", "as", "is", "was", "it",
    "i", "uh", "um", "but", "so", "be", "are", "by", "with", "from", "that", "this", "we",
    "you", "he", "she", "they", "my", "our", "can", "do", "does", "will", "would", "have", "has",
}
VOWEL_PAIRS = {("ɪ", "iː"): "ɪ-iː", ("iː", "ɪ"): "ɪ-iː", ("i", "ɪ"): "ɪ-iː", ("ɪ", "i"): "ɪ-iː",
               ("æ", "ɛ"): "æ-ɛ", ("ɛ", "æ"): "æ-ɛ", ("æ", "e"): "æ-ɛ"}
TECH_K_DELTA = 0.5  # technical terms: k - 0.5 (stricter)
MIN_K = 1.0


@dataclass(frozen=True)
class Stats:
    mean: float
    std: float


@dataclass
class Calibration:
    """Native score distribution per phoneme, with a global fallback for unseen phones."""

    per_phone: dict[str, Stats]
    fallback: Stats = Stats(mean=2.5, std=2.0)  # replaced by the global calibration stats

    def get(self, phone: str) -> Stats:
        return self.per_phone.get(phone, self.fallback)


@dataclass
class Variants:
    general: set[tuple[str, str]] = field(default_factory=set)  # (expected, accepted) single phones
    by_word: dict[str, list[list[str]]] = field(default_factory=dict)  # word → accepted sequences


@dataclass
class Context:
    calibration: Calibration
    variants: Variants
    k: float = 2.0
    offsets: dict[tuple[str, str | None], float] = field(default_factory=dict)  # (phone, word|None)
    tech_terms: set[str] = field(default_factory=set)
    pronunciations: dict[str, list[str]] = field(default_factory=dict)  # curated G2P (tech vocabulary)


@dataclass
class Candidate:
    word: str
    word_index: int  # position in the turn's asr_words
    category: str
    expected: str  # expected phones of the word (space separated)
    heard: str  # heard phones of the word (space separated)
    phone: str  # the phone in question ("" for insertions)
    heard_phone: str  # what was heard instead ("" for omissions)
    phone_index: int | None
    score: float | None
    threshold: float | None
    is_tech: bool
    start_ms: int | None = None
    end_ms: int | None = None

    @property
    def strength(self) -> float:
        """How far below the threshold (bigger = more certain). Insertions get a fixed 1.0."""
        if self.score is None or self.threshold is None:
            return 1.0
        return self.threshold - self.score


def threshold(ctx: Context, phone: str, word: str) -> float:
    stats = ctx.calibration.get(phone)
    k = max(MIN_K, ctx.k - TECH_K_DELTA) if word in ctx.tech_terms else ctx.k
    # user tolerance: per phoneme, plus extra for this specific word
    offset = ctx.offsets.get((phone, None), 0.0) + ctx.offsets.get((phone, word), 0.0)
    return stats.mean - k * stats.std - offset


def category_for(edit_expected: str | None, heard: str | None) -> str:
    if edit_expected is None:
        return "pron:epenthesis"
    pair = VOWEL_PAIRS.get((edit_expected, heard or ""))
    if pair:
        return f"pron:vowel:{pair}"
    if edit_expected in VOWELS and heard in VOWELS:
        return f"pron:vowel:{edit_expected}-{heard}"
    return f"pron:phoneme:{edit_expected}"


def _matches_word_variant(ctx: Context, word: str, expected: list[str], heard: list[str]) -> bool:
    for accepted in ctx.variants.by_word.get(word, []):
        if distance(accepted, heard) < distance(expected, heard):
            return True
    return False


def judge_word(
    ctx: Context, word: str, word_index: int, result: dict, next_word_phones: list[str] | None = None,
) -> list[Candidate]:
    """Error candidates for one word, from the model server's per-word result."""
    norm = word.lower().strip(".,!?;:\"'()")
    if not result.get("aligned") or norm in FUNCTION_WORDS or not norm:
        return []
    if any(ch.isdigit() for ch in norm):  # "2021", "p99": read in many valid ways
        return []
    phones = [p for p in result["phones"] if not p.get("unknown")]
    expected = [p["p"] for p in phones]
    heard: list[str] = result["heard"]
    if not expected or _matches_word_variant(ctx, norm, expected, heard):
        return []

    edits = align(expected, heard)
    by_index: dict[int, Edit] = {e.index: e for e in edits if e.index is not None}
    out: list[Candidate] = []
    base = dict(word=word, word_index=word_index, expected=" ".join(expected), heard=" ".join(heard),
                is_tech=norm in ctx.tech_terms, start_ms=result.get("start_ms"), end_ms=result.get("end_ms"))

    for i, p in enumerate(phones):
        thr = threshold(ctx, p["p"], norm)
        if p["score"] >= thr:
            continue
        edit = by_index.get(i)
        heard_phone = edit.heard if edit and edit.op == "sub" else ("" if edit and edit.op == "del" else p["competitor"])
        if heard_phone and (p["p"], heard_phone) in ctx.variants.general:
            continue
        category = category_for(p["p"], heard_phone or None)
        out.append(Candidate(**base, category=category, phone=p["p"], heard_phone=heard_phone,
                             phone_index=i, score=p["score"], threshold=round(thr, 3)))

    out += _insertions(norm, expected, edits, base, next_word_phones)
    return out


def _insertions(norm: str, expected: list[str], edits: list[Edit], base: dict,
                next_word_phones: list[str] | None) -> list[Candidate]:
    """Epenthetic vowels: "es-tack" (before initial s + consonant), "Goo-gui-li" (after a final
    consonant), and "-ed" pronounced as a syllable."""
    out = []
    for e in edits:
        if e.op != "ins" or e.heard not in EPENTHETIC:
            continue
        if e.before == 0 and len(expected) > 1 and expected[0] == "s" and expected[1] not in VOWELS:
            category = "pron:epenthesis"
        elif e.before == len(expected) and expected[-1] not in VOWELS:
            if next_word_phones and next_word_phones[0] in VOWELS:
                continue  # probably the next word's vowel bleeding into this window
            category = "pron:epenthesis"
        elif (norm.endswith("ed") and e.before == len(expected) - 1 and expected[-1] in ("d", "t")
              and (len(expected) < 2 or expected[-2] not in VOWELS)):
            category = "pron:final_ed"
        else:
            continue
        out.append(Candidate(**base, category=category, phone="", heard_phone=e.heard,
                             phone_index=e.before, score=None, threshold=None))
    return out
