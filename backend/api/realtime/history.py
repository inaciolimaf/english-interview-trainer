"""Conversation history for the LLM, including interruptions (section 7.6)."""

from dataclasses import dataclass

from api.llm.client import Message

KICKOFF = "[The candidate has joined the call. Start the interview.]"


@dataclass
class TurnRecord:
    role: str  # "interviewer" | "candidate"
    full_text: str
    spoken_text: str
    interrupted: bool = False


def join_sentences(sentences: list[str]) -> str:
    return " ".join(s.strip() for s in sentences if s.strip())


def spoken_prefix(sentences: list[str], sentence_idx: int, char_offset: int) -> str:
    """Text actually heard: every sentence before ``sentence_idx`` plus the first
    ``char_offset`` chars of that sentence, extended to the end of a cut word."""
    if sentence_idx >= len(sentences):
        return join_sentences(sentences)
    current = sentences[sentence_idx]
    end = max(0, min(char_offset, len(current)))
    while 0 < end < len(current) and not current[end].isspace() and not current[end - 1].isspace():
        end += 1
    return join_sentences([*sentences[:sentence_idx], current[:end].rstrip()])


def build_messages(system_prompt: str, turns: list[TurnRecord]) -> list[Message]:
    messages: list[Message] = [{"role": "system", "content": system_prompt}]
    if not turns:
        return [*messages, {"role": "user", "content": KICKOFF}]
    if turns[0].role == "interviewer":
        messages.append({"role": "user", "content": KICKOFF})

    for turn in turns:
        if turn.role == "candidate":
            _append(messages, "user", turn.spoken_text)
        elif not turn.interrupted:
            _append(messages, "assistant", turn.full_text)
        else:
            unsaid = turn.full_text[len(turn.spoken_text):].strip()
            _append(messages, "assistant", f"{turn.spoken_text}—")
            messages.append({
                "role": "system",
                "content": (
                    "[The candidate interrupted you at this point. They did NOT hear the rest "
                    f"of what you planned to say: '{unsaid}'. Respond naturally to what they said.]"
                ),
            })
    return messages


def _append(messages: list[Message], role: str, content: str) -> None:
    """Merge consecutive messages of the same role (e.g. a candidate turn that resumed)."""
    content = content.strip()
    if not content:
        return
    if messages[-1]["role"] == role and role != "system":
        messages[-1] = {"role": role, "content": f"{messages[-1]['content']} {content}"}
    else:
        messages.append({"role": role, "content": content})
