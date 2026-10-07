import type { TtsWord } from "../realtime/protocol";
import { charOffsetAt } from "./charOffset";
import { analyserLevel } from "./level";

const DUCK_GAIN = 0.2;

interface Scheduled {
  turnId: number;
  idx: number;
  text: string;
  words: TtsWord[];
  startTime: number; // AudioContext time
  duration: number; // seconds
  source: AudioBufferSourceNode;
}

export interface PlaybackPosition {
  sentenceIdx: number;
  charOffset: number;
}

/**
 * Plays the interviewer's sentences back to back and knows, at any moment, which
 * word is being heard (for barge-in). Sentences of stale turns are dropped.
 */
export class Player {
  private ctx = new AudioContext();
  private gain = this.ctx.createGain();
  private analyser = this.ctx.createAnalyser();
  private levelBuf = new Float32Array(512);
  private queue: Scheduled[] = [];
  private pendingMeta = new Map<string, { text: string; words: TtsWord[]; sampleRate: number }>();
  private expected = new Map<number, number>(); // turnId -> n_sentences (after tts_end)
  private finished = new Map<number, number>(); // turnId -> sentences finished playing
  private minTurnId = 0;

  /** Called when every sentence of a turn has finished playing. */
  onTurnPlayed: (turnId: number) => void = () => {};
  /** Called with the text of each sentence as it starts playing. */
  onSentenceStart: (turnId: number, idx: number, text: string) => void = () => {};

  constructor() {
    this.gain.connect(this.ctx.destination);
    this.analyser.fftSize = 512;
    this.gain.connect(this.analyser);
  }

  /** Loudness of what is playing right now (0–1), for the voice ring. */
  level(): number {
    return this.isPlaying ? analyserLevel(this.analyser, this.levelBuf) : 0;
  }

  async resume(): Promise<void> {
    if (this.ctx.state !== "running") await this.ctx.resume();
  }

  addSentenceMeta(turnId: number, idx: number, text: string, words: TtsWord[], sampleRate: number): void {
    if (turnId < this.minTurnId) return;
    this.pendingMeta.set(`${turnId}:${idx}`, { text, words, sampleRate });
  }

  addAudio(turnId: number, idx: number, pcm: Int16Array): void {
    const key = `${turnId}:${idx}`;
    const meta = this.pendingMeta.get(key);
    this.pendingMeta.delete(key);
    if (turnId < this.minTurnId || !meta) return;

    const buffer = this.ctx.createBuffer(1, pcm.length, meta.sampleRate);
    const channel = buffer.getChannelData(0);
    for (let i = 0; i < pcm.length; i++) channel[i] = pcm[i] / 32768;

    const source = this.ctx.createBufferSource();
    source.buffer = buffer;
    source.connect(this.gain);
    const last = this.queue[this.queue.length - 1];
    const startTime = Math.max(this.ctx.currentTime + 0.02, last ? last.startTime + last.duration : 0);
    const item: Scheduled = { turnId, idx, text: meta.text, words: meta.words, startTime, duration: buffer.duration, source };
    this.queue.push(item);

    const delayMs = Math.max(0, (startTime - this.ctx.currentTime) * 1000);
    window.setTimeout(() => {
      if (this.queue.includes(item)) this.onSentenceStart(turnId, idx, meta.text);
    }, delayMs);
    source.onended = () => this.handleEnded(item);
    source.start(startTime);
  }

  /** Server finished generating this turn: playback_done fires after its last sentence. */
  endOfTurn(turnId: number, nSentences: number): void {
    if (turnId < this.minTurnId) return;
    this.expected.set(turnId, nSentences);
    this.checkTurnDone(turnId);
  }

  /** Where the listener is right now in the current turn's audio. */
  position(): PlaybackPosition {
    const now = this.ctx.currentTime;
    const playing = this.queue.find((s) => now >= s.startTime && now < s.startTime + s.duration);
    if (playing) {
      const elapsedMs = (now - playing.startTime) * 1000;
      return { sentenceIdx: playing.idx, charOffset: charOffsetAt(playing.words, elapsedMs, playing.text.length) };
    }
    const upcoming = this.queue.find((s) => s.startTime > now);
    if (upcoming) return { sentenceIdx: upcoming.idx, charOffset: 0 };
    const last = this.queue[this.queue.length - 1];
    return last ? { sentenceIdx: last.idx, charOffset: last.text.length } : { sentenceIdx: 0, charOffset: 0 };
  }

  /** Stop everything of `turnId` (and older) immediately; returns where it stopped. */
  stop(turnId: number): PlaybackPosition {
    const pos = this.position();
    this.minTurnId = Math.max(this.minTurnId, turnId + 1);
    for (const item of this.queue) {
      item.source.onended = null;
      try {
        item.source.stop();
      } catch {
        // already stopped
      }
    }
    this.queue = [];
    this.pendingMeta.clear();
    this.unduck();
    return pos;
  }

  /** New connection: stop everything and accept turn ids from 0 again. */
  reset(): void {
    this.stop(Number.MAX_SAFE_INTEGER - 1);
    this.expected.clear();
    this.finished.clear();
    this.minTurnId = 0;
  }

  get isPlaying(): boolean {
    return this.queue.length > 0;
  }

  duck(): void {
    this.gain.gain.setTargetAtTime(DUCK_GAIN, this.ctx.currentTime, 0.015);
  }

  unduck(): void {
    this.gain.gain.setTargetAtTime(1, this.ctx.currentTime, 0.05);
  }

  async close(): Promise<void> {
    this.stop(Number.MAX_SAFE_INTEGER - 1);
    await this.ctx.close();
  }

  private handleEnded(item: Scheduled): void {
    this.queue = this.queue.filter((s) => s !== item);
    this.finished.set(item.turnId, (this.finished.get(item.turnId) ?? 0) + 1);
    this.checkTurnDone(item.turnId);
  }

  private checkTurnDone(turnId: number): void {
    const expected = this.expected.get(turnId);
    if (expected !== undefined && (this.finished.get(turnId) ?? 0) >= expected) {
      this.expected.delete(turnId);
      this.finished.delete(turnId);
      this.onTurnPlayed(turnId);
    }
  }
}
