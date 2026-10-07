import { openMicrophone, PcmCapture } from "./capture";
import { pcmLevel } from "./level";

/** Records the mic as one PCM16 16 kHz buffer (drill attempts). */
export class Recorder {
  private stream: MediaStream | null = null;
  private capture: PcmCapture | null = null;
  private frames: ArrayBuffer[] = [];
  /** Loudness of the latest 20 ms frame (0–1), for a level meter. */
  level = 0;

  async start(): Promise<void> {
    this.frames = [];
    this.stream = await openMicrophone();
    this.capture = new PcmCapture();
    await this.capture.start(this.stream, (pcm) => {
      this.frames.push(pcm);
      this.level = pcmLevel(pcm);
    });
  }

  async stop(): Promise<ArrayBuffer> {
    await this.capture?.stop();
    this.stream?.getTracks().forEach((t) => t.stop());
    this.capture = null;
    this.stream = null;
    const total = this.frames.reduce((n, f) => n + f.byteLength, 0);
    const out = new Uint8Array(total);
    let offset = 0;
    for (const f of this.frames) {
      out.set(new Uint8Array(f), offset);
      offset += f.byteLength;
    }
    this.frames = [];
    this.level = 0;
    return out.buffer;
  }
}
