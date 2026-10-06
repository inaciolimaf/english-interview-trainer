// Mirrors backend/api/realtime/PROTOCOL.md

export type ServerState = "IDLE" | "LISTENING" | "THINKING" | "SPEAKING" | "DUCKING";
export type TurnTakingMode = "auto" | "push_to_talk";

export interface TtsWord {
  w: string;
  start_ms: number;
  end_ms: number;
  char_start: number;
  char_end: number;
}

export interface LiveFeedbackItem {
  error_id: string;
  kind: "pronunciation" | "grammar" | "technical" | "fluency" | "vocabulary";
  category: string;
  severity: "low" | "medium" | "high";
  original_text: string | null;
  corrected_text: string | null;
  explanation: string | null;
  word: string | null;
}

export type ServerMessage =
  | { type: "config"; turn_taking_mode: TurnTakingMode; turn_id: number }
  | { type: "state"; state: ServerState; turn_id: number }
  | { type: "transcript_partial" | "transcript_final"; text: string }
  | {
      type: "tts_sentence";
      turn_id: number;
      sentence_idx: number;
      text: string;
      words: TtsWord[];
      sample_rate: number;
    }
  | { type: "tts_end"; turn_id: number; n_sentences: number }
  | { type: "stop_playback"; turn_id: number }
  | { type: "duck" | "unduck" }
  | { type: "time"; remaining_s: number }
  | {
      type: "latency";
      turn_id: number;
      end_of_turn_wait_ms: number;
      llm_first_token_ms: number | null;
      first_sentence_ms: number | null;
      first_audio_ms: number | null;
      total_ms: number;
    }
  | { type: "error" | "warning"; message: string }
  | { type: "live_feedback"; turn_idx: number; items: LiveFeedbackItem[] }
  | { type: "session_ended"; session_id: string };

export type ClientMessage =
  | { type: "vad"; event: "speech_start" | "speech_end"; t: number }
  | { type: "ptt"; event: "down" | "up" }
  | { type: "interrupted"; turn_id: number; sentence_idx: number; char_offset: number }
  | { type: "playback_done"; turn_id: number }
  | { type: "set_mode"; mode: TurnTakingMode }
  | { type: "end_session" };

/** Binary audio from the server: 8-byte little-endian header + PCM16 mono. */
export const AUDIO_HEADER_BYTES = 8;

export function parseAudioFrame(buf: ArrayBuffer): { turnId: number; sentenceIdx: number; pcm: Int16Array } {
  const view = new DataView(buf);
  return {
    turnId: view.getUint32(0, true),
    sentenceIdx: view.getUint16(4, true),
    pcm: new Int16Array(buf, AUDIO_HEADER_BYTES),
  };
}
