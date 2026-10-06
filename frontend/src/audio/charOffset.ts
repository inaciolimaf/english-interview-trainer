import type { TtsWord } from "../realtime/protocol";

/**
 * Character offset (within the sentence) of what the listener has heard after
 * `elapsedMs` of playback. A word counts as heard once more than half of it played.
 */
export function charOffsetAt(words: TtsWord[], elapsedMs: number, textLength: number): number {
  if (words.length === 0) return elapsedMs > 0 ? textLength : 0;
  let offset = 0;
  for (const word of words) {
    const midpoint = (word.start_ms + word.end_ms) / 2;
    if (elapsedMs < midpoint) break;
    offset = word.char_end;
  }
  return offset;
}
