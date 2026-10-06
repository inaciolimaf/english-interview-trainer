import type { MicVAD } from "@ricky0123/vad-web";
import { openMicrophone, PcmCapture } from "../audio/capture";
import { Player } from "../audio/player";
import { startVad } from "../audio/vad";
import {
  parseAudioFrame,
  type ClientMessage,
  type ServerMessage,
  type ServerState,
  type TurnTakingMode,
} from "./protocol";

export interface InterviewEvents {
  onState: (state: ServerState) => void;
  onMessage: (msg: ServerMessage) => void;
  onSentencePlayed: (turnId: number, idx: number, text: string) => void;
  onConnection: (status: "connecting" | "open" | "reconnecting" | "closed") => void;
}

const RECONNECT_DELAYS_MS = [500, 1000, 2000, 4000, 8000];

/**
 * Client side of the realtime interview (section 7). Mirrors the server state; does
 * the latency-critical parts locally: ducking on speech, stopping playback, tracking
 * the word being heard.
 */
export class InterviewClient {
  private ws: WebSocket | null = null;
  private stream: MediaStream | null = null;
  private capture: PcmCapture | null = null;
  private vad: MicVAD | null = null;
  private player = new Player();
  private state: ServerState = "IDLE";
  private mode: TurnTakingMode = "auto";
  private ended = false;
  private attempt = 0;
  private pttDown = false;

  constructor(
    private sessionId: string,
    private events: InterviewEvents,
  ) {
    this.player.onTurnPlayed = (turnId) => this.send({ type: "playback_done", turn_id: turnId });
    this.player.onSentenceStart = (turnId, idx, text) => this.events.onSentencePlayed(turnId, idx, text);
  }

  /** Must be called from a user gesture (mic permission + audio autoplay). */
  async start(): Promise<void> {
    await this.player.resume();
    this.stream = await openMicrophone();
    this.capture = new PcmCapture();
    await this.capture.start(this.stream, (pcm) => {
      if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(pcm);
    });
    this.vad = await startVad(this.stream, {
      onSpeechStart: () => this.onLocalSpeechStart(),
      onSpeechEnd: () => this.mode === "auto" && this.send({ type: "vad", event: "speech_end", t: Date.now() }),
    });
    this.connect();
  }

  setMode(mode: TurnTakingMode): void {
    this.mode = mode;
    this.send({ type: "set_mode", mode });
  }

  pushToTalk(down: boolean): void {
    if (this.mode !== "push_to_talk" || down === this.pttDown) return;
    this.pttDown = down;
    if (down && this.player.isPlaying) this.player.duck();
    this.send({ type: "ptt", event: down ? "down" : "up" });
  }

  endSession(): void {
    this.send({ type: "end_session" });
  }

  async close(): Promise<void> {
    this.ended = true;
    this.ws?.close();
    await this.vad?.destroy();
    await this.capture?.stop();
    this.stream?.getTracks().forEach((t) => t.stop());
    await this.player.close();
    this.events.onConnection("closed");
  }

  private connect(): void {
    this.events.onConnection(this.attempt === 0 ? "connecting" : "reconnecting");
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/ws/interview/${this.sessionId}`);
    ws.binaryType = "arraybuffer";
    ws.onopen = () => {
      this.attempt = 0;
      this.events.onConnection("open");
    };
    ws.onmessage = (e) => {
      if (e.data instanceof ArrayBuffer) {
        const { turnId, sentenceIdx, pcm } = parseAudioFrame(e.data);
        this.player.addAudio(turnId, sentenceIdx, pcm);
      } else {
        this.handle(JSON.parse(e.data) as ServerMessage);
      }
    };
    ws.onclose = () => {
      if (this.ended) return;
      // the server resumes from the saved turns and restarts turn ids at 0
      this.player.reset();
      const delay = RECONNECT_DELAYS_MS[Math.min(this.attempt++, RECONNECT_DELAYS_MS.length - 1)];
      this.events.onConnection("reconnecting");
      window.setTimeout(() => this.connect(), delay);
    };
    this.ws = ws;
  }

  private handle(msg: ServerMessage): void {
    switch (msg.type) {
      case "state":
        this.state = msg.state;
        this.events.onState(msg.state);
        break;
      case "config":
        this.mode = msg.turn_taking_mode;
        break;
      case "tts_sentence":
        this.player.addSentenceMeta(msg.turn_id, msg.sentence_idx, msg.text, msg.words, msg.sample_rate);
        break;
      case "tts_end":
        this.player.endOfTurn(msg.turn_id, msg.n_sentences);
        break;
      case "stop_playback": {
        const pos = this.player.stop(msg.turn_id);
        this.send({ type: "interrupted", turn_id: msg.turn_id, sentence_idx: pos.sentenceIdx, char_offset: pos.charOffset });
        break;
      }
      case "duck":
        this.player.duck();
        break;
      case "unduck":
        this.player.unduck();
        break;
      case "session_ended":
        this.ended = true;
        break;
    }
    this.events.onMessage(msg);
  }

  private onLocalSpeechStart(): void {
    if (this.mode !== "auto") return;
    // duck right away; the server decides whether it is a real interruption
    if (this.state === "SPEAKING" || this.player.isPlaying) this.player.duck();
    this.send({ type: "vad", event: "speech_start", t: Date.now() });
  }

  private send(msg: ClientMessage): void {
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(msg));
  }
}
