import workletUrl from "./captureWorklet.ts?worker&url";

export const CAPTURE_SAMPLE_RATE = 16_000;

/** Microphone stream with the browser's echo cancellation (needed without headphones). */
export function openMicrophone(): Promise<MediaStream> {
  return navigator.mediaDevices.getUserMedia({
    audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 },
  });
}

/** Streams the mic as PCM16 mono 16 kHz frames of 20 ms. */
export class PcmCapture {
  private ctx = new AudioContext({ sampleRate: CAPTURE_SAMPLE_RATE });
  private node: AudioWorkletNode | null = null;

  async start(stream: MediaStream, onFrame: (pcm: ArrayBuffer) => void): Promise<void> {
    await this.ctx.audioWorklet.addModule(workletUrl);
    const source = this.ctx.createMediaStreamSource(stream);
    this.node = new AudioWorkletNode(this.ctx, "pcm-capture");
    this.node.port.onmessage = (e: MessageEvent<ArrayBuffer>) => onFrame(e.data);
    source.connect(this.node);
    await this.ctx.resume();
  }

  async stop(): Promise<void> {
    this.node?.disconnect();
    await this.ctx.close();
  }
}
