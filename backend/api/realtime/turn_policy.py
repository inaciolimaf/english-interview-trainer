"""End-of-turn and barge-in decisions (sections 7.4 and 7.5). Pure functions — no I/O."""

import re
from dataclasses import dataclass
from enum import StrEnum


@dataclass(frozen=True)
class TurnPolicy:
    check_after_ms: int = 600  # first look at the model after this much silence
    silence_ms: int = 1500  # user_settings.end_of_turn_silence_ms
    max_silence_ms: int = 4000  # always end the turn after this much silence
    high_prob: float = 0.8  # model confident the turn is over → answer at check_after_ms
    low_prob: float = 0.5  # model unsure → answer at silence_ms; below → wait for max
    # Whisper put a sentence-final mark and the phrase isn't hanging: a much weaker model
    # vote is enough to answer at silence_ms (with real voices Smart Turn often says ~0.2–0.3)
    punctuated_prob: float = 0.15
    bargein_min_ms: int = 400  # shorter speech during SPEAKING is a cough/noise
    bargein_max_wait_ms: int = 1500  # backchannels are short; still speaking → interruption
    bargein_recheck_ms: int = 300  # re-transcribe the interrupting speech this often


class Decision(StrEnum):
    END = "end"
    WAIT = "wait"


# Last words that make a phrase clearly unfinished ("...and then", "so I would use")
INCOMPLETE_ENDINGS = {
    "and", "or", "but", "so", "because", "then", "the", "a", "an", "to", "of", "with", "for",
    "in", "on", "at", "by", "from", "that", "which", "who", "if", "when", "while", "like",
    "um", "uh", "er", "my", "our", "your", "their", "its", "is", "are", "was", "were", "be",
    "would", "will", "can", "could", "should", "might", "i", "we", "also", "about", "into",
    "than", "as", "this", "these", "those", "more", "very", "really", "maybe", "between",
}
MODALS = {"would", "will", "can", "could", "should", "might", "i'd", "we'd", "i'll", "we'll"}
_WORDS = re.compile(r"[a-z']+")


def is_incomplete(transcript: str) -> bool:
    text = transcript.strip().lower()
    if not text:
        return False
    if text.endswith(("...", "…", ",", "-", "—")):
        return True
    words = _WORDS.findall(text)
    if not words:
        return False
    if words[-1] in INCOMPLETE_ENDINGS:
        return True
    # "...I would use" / "we could implement": modal + bare verb at the very end
    return len(words) >= 2 and words[-2] in MODALS


def decide_end_of_turn(
    policy: TurnPolicy, silence_ms: float, probability: float | None, transcript: str
) -> Decision:
    if silence_ms >= policy.max_silence_ms:
        return Decision.END
    if silence_ms < policy.check_after_ms or is_incomplete(transcript):
        return Decision.WAIT
    if probability is None:  # detector unavailable: fall back to plain silence
        return Decision.END if silence_ms >= policy.silence_ms else Decision.WAIT
    if probability >= policy.high_prob:
        return Decision.END
    if silence_ms >= policy.silence_ms:
        if probability >= policy.low_prob:
            return Decision.END
        if probability >= policy.punctuated_prob and re.search(r"[.!?][\"')]*$", transcript.strip()):
            return Decision.END
    return Decision.WAIT


DEFAULT_BACKCHANNELS = (
    "yeah", "yes", "yep", "yup", "right", "uh-huh", "uh huh", "okay", "ok", "mm-hmm", "mhm",
    "mm hmm", "hmm", "mm", "got it", "sure", "i see", "alright", "all right", "cool", "great",
    "nice", "exactly", "makes sense", "true",
)


def is_backchannel(transcript: str, phrases: tuple[str, ...] = DEFAULT_BACKCHANNELS) -> bool:
    """True when the WHOLE utterance is backchannel (possibly repeated: "yeah, yeah")."""
    text = re.sub(r"[^a-z' -]", " ", transcript.lower()).replace("-", " ")
    text = " ".join(text.split())
    if not text:
        return True  # nothing intelligible: don't interrupt
    alternatives = "|".join(
        re.escape(" ".join(p.replace("-", " ").split()))
        for p in sorted(phrases, key=len, reverse=True)
    )
    return re.fullmatch(rf"(?:{alternatives})(?: (?:{alternatives}))*", text) is not None


# Words people open an interruption with — enough on their own to stop the interviewer
INTERRUPTION_OPENERS = {"sorry", "wait", "actually", "excuse", "hold", "but", "pardon", "hang"}


def is_substantive(transcript: str, phrases: tuple[str, ...] = DEFAULT_BACKCHANNELS) -> bool:
    """Enough real words to call it an interruption before the speaker has finished.

    Partial snippets of a backchannel often come out as junk ("E.H." for "uh-"), so one
    stray token is not enough: require two real words that aren't backchannel, or a
    typical interruption opener ("Sorry", "Wait").
    """
    words = [w for w in _WORDS.findall(transcript.lower()) if len(w) > 1 or w in ("i", "a")]
    if words and words[0] in INTERRUPTION_OPENERS:
        return True
    return len(words) >= 2 and not is_backchannel(transcript, phrases)
