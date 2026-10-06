import { MicVAD } from "@ricky0123/vad-web";

/** Must match VAD_REDEMPTION_MS in backend/api/realtime/orchestrator.py. */
export const VAD_REDEMPTION_MS = 300;

export interface VadCallbacks {
  onSpeechStart: () => void;
  onSpeechEnd: () => void;
}

/**
 * Absolute URL (with origin) of the assets copied to public/vad/. onnxruntime-web loads its
 * .mjs with a dynamic import(); in dev, Vite rewrites root-relative import URLs ("/vad/…" →
 * "/vad/…?import") and refuses to serve public files that way. Full URLs are left alone.
 */
const VAD_ASSETS = new URL("/vad/", window.location.origin).href;

/** Silero VAD (v5, ONNX in the browser) on the shared microphone stream. */
export async function startVad(stream: MediaStream, cb: VadCallbacks): Promise<MicVAD> {
  const vad = await MicVAD.new({
    model: "v5",
    baseAssetPath: VAD_ASSETS,
    onnxWASMBasePath: VAD_ASSETS,
    getStream: async () => stream,
    positiveSpeechThreshold: 0.5,
    negativeSpeechThreshold: 0.35,
    redemptionMs: VAD_REDEMPTION_MS,
    minSpeechMs: 150,
    preSpeechPadMs: 300,
    onSpeechStart: cb.onSpeechStart,
    onSpeechEnd: () => cb.onSpeechEnd(),
    // speech shorter than minSpeechMs: still tell the server it ended (it's noise)
    onVADMisfire: cb.onSpeechEnd,
  });
  vad.start();
  return vad;
}
