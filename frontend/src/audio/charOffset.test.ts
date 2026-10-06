import { describe, expect, it } from "vitest";
import type { TtsWord } from "../realtime/protocol";
import { charOffsetAt } from "./charOffset";

// "Tell me about caching."
const WORDS: TtsWord[] = [
  { w: "Tell", start_ms: 100, end_ms: 300, char_start: 0, char_end: 4 },
  { w: "me", start_ms: 300, end_ms: 400, char_start: 5, char_end: 7 },
  { w: "about", start_ms: 400, end_ms: 700, char_start: 8, char_end: 13 },
  { w: "caching", start_ms: 700, end_ms: 1200, char_start: 14, char_end: 21 },
];
const LEN = "Tell me about caching.".length;

describe("charOffsetAt", () => {
  it("is 0 before the first word is half spoken", () => {
    expect(charOffsetAt(WORDS, 0, LEN)).toBe(0);
    expect(charOffsetAt(WORDS, 199, LEN)).toBe(0);
  });

  it("includes a word once past its midpoint", () => {
    expect(charOffsetAt(WORDS, 200, LEN)).toBe(4);
    expect(charOffsetAt(WORDS, 549, LEN)).toBe(7);
    expect(charOffsetAt(WORDS, 550, LEN)).toBe(13);
  });

  it("covers the whole sentence at the end", () => {
    expect(charOffsetAt(WORDS, 5000, LEN)).toBe(21);
  });

  it("falls back to all-or-nothing without word timings", () => {
    expect(charOffsetAt([], 0, LEN)).toBe(0);
    expect(charOffsetAt([], 10, LEN)).toBe(LEN);
  });
});
