# Realtime interview protocol

WebSocket: `ws://localhost:8000/ws/interview/{session_id}` (the Vite dev server proxies `/ws`).
Create the session first with `POST /api/sessions`. Closing with code `4404` means the session
does not exist.

Implementation: `orchestrator.py` (server, source of truth) and
`frontend/src/realtime/client.ts` (client, mirrors the state).

## Frames

| Direction | Text frames | Binary frames |
|---|---|---|
| client → server | JSON messages below | Microphone audio: raw PCM16 little-endian, mono, **16 kHz**, ~20 ms per frame, sent continuously (also while the interviewer speaks) |
| server → client | JSON messages below | Interviewer audio: **8-byte header** + PCM16 little-endian mono at the `sample_rate` of the matching `tts_sentence` (24 kHz) |

Audio header (little-endian): `uint32 turn_id`, `uint16 sentence_idx`, `uint16 reserved (0)`.
Every `tts_sentence` JSON is immediately followed by its binary frame.

## State machine

```
IDLE → LISTENING → THINKING → SPEAKING → LISTENING          (normal turn)
       THINKING ── candidate speaks again ──▶ LISTENING       (reply dropped, turn reopened)
       SPEAKING ── VAD speech ──▶ DUCKING ──▶ SPEAKING         (noise < 400 ms / backchannel)
                                     └──────▶ LISTENING        (interruption confirmed)
```

`turn_id` identifies one interviewer reply and only grows. It also increases when an
interruption is confirmed. Both sides drop anything that belongs to an older turn. Turn ids
start again at 1 on every connection; the conversation itself is reloaded from the database.

## Client → server

| Message | When |
|---|---|
| `{type:"vad", event:"speech_start"\|"speech_end", t}` | Silero VAD in the browser (hands-free mode). `speech_end` arrives `VAD_REDEMPTION_MS` (300 ms) after the speech stopped; misfires (speech < 150 ms) also send `speech_end`. `t` = client epoch ms, informative only — the server places events by how many audio samples it has received. |
| `{type:"ptt", event:"down"\|"up"}` | Push-to-talk (Space). `down` while the interviewer speaks interrupts right away; `up` ends the turn immediately. |
| `{type:"interrupted", turn_id, sentence_idx, char_offset}` | Reply to `stop_playback`: where the listener was. `char_offset` is within that sentence's text; a word counts as heard once past its midpoint. |
| `{type:"playback_done", turn_id}` | Every sentence of the turn (announced by `tts_end`) finished playing. |
| `{type:"set_mode", mode:"auto"\|"push_to_talk"}` | Switch turn taking during the session. *(Extension to spec 7.7.)* |
| `{type:"end_session"}` | The server marks the session `completed`, answers `session_ended` and closes. |

## Server → client

| Message | Meaning |
|---|---|
| `{type:"config", turn_taking_mode, turn_id}` | Sent on connect and after `set_mode`. *(Extension.)* |
| `{type:"state", state, turn_id}` | The new state, with the current `turn_id`. |
| `{type:"transcript_partial", text}` | The candidate's turn so far (each VAD segment is transcribed as soon as it ends). |
| `{type:"transcript_final", text}` | The turn ended; the interviewer is about to answer. If the candidate keeps talking during `THINKING`, the turn is reopened and more partials follow. |
| `{type:"tts_sentence", turn_id, sentence_idx, text, words, sample_rate}` + binary | One sentence of the reply. `words[]`: `{w, start_ms, end_ms, char_start, char_end}`, with times relative to the sentence audio and character ranges into `text`. |
| `{type:"tts_end", turn_id, n_sentences}` | No more sentences for this turn. *(Extension: lets the client know when to send `playback_done`.)* |
| `{type:"duck"}` / `{type:"unduck"}` | Lower the volume to 20% / restore it. The client ducks on its own at `speech_start`; `unduck` means it was noise or a backchannel. |
| `{type:"stop_playback", turn_id}` | Interruption confirmed: stop at once, drop the buffer, answer with `interrupted`. *(Extension: the server makes the decision because it has the transcript.)* |
| `{type:"time", remaining_s}` | Every 10 s. |
| `{type:"latency", turn_id, end_of_turn_wait_ms, llm_first_token_ms, first_sentence_ms, first_audio_ms, total_ms}` | Timings of the reply that just started. `total_ms` = end of the candidate's speech → first audio sent. *(Extension.)* |
| `{type:"warning", message}` | For example, an LLM retry is in progress. *(Extension.)* |
| `{type:"error", message}` | Model server or LLM failure; the state returns to `LISTENING`. *(Extension.)* |
| `{type:"live_feedback", turn_idx, items}` | Reserved for spec 04 (section 10.1). |
| `{type:"session_ended", session_id}` | After `end_session`. |

## Timing rules (`turn_policy.py`)

End of turn (section 7.4), measured from the end of speech:

- before 600 ms of silence → wait;
- phrase clearly unfinished ("…and then", "so I would use") → wait until 4 s;
- Smart Turn P(complete) ≥ 0.8 → answer at 600 ms;
- P ≥ 0.5 → answer at `end_of_turn_silence_ms` (1.5 s by default);
- otherwise → answer at 4 s.

Barge-in (section 7.5), while the interviewer is speaking:

- speech under 400 ms → noise, `unduck`;
- from 400 ms, the speech is transcribed every ~300 ms; two real words that are not a
  backchannel, or an opener such as "sorry" or "wait" → interruption;
- speech ends and the whole utterance is a backchannel ("yeah", "got it", "uh-huh"…) → `unduck`;
- still talking after 1.5 s → interruption.

On a confirmed interruption, the server cancels the LLM stream and the pending TTS at once,
then waits up to 1.5 s for `interrupted` to store `spoken_text`. If no report arrives, it
assumes that every sentence already sent was heard.
