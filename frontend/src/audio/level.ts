/** Loudness of a PCM16 frame mapped to 0–1 (≈ -60 dBFS → 0, ≈ -10 dBFS → 1), for meters. */
export function pcmLevel(pcm: ArrayBuffer): number {
  const samples = new Int16Array(pcm);
  if (samples.length === 0) return 0;
  let sum = 0;
  for (let i = 0; i < samples.length; i++) {
    const s = samples[i] / 32768;
    sum += s * s;
  }
  const db = 20 * Math.log10(Math.sqrt(sum / samples.length) || 1e-9);
  return Math.min(1, Math.max(0, (db + 60) / 50));
}

/** Same scale for an AnalyserNode (time-domain float data). */
export function analyserLevel(analyser: AnalyserNode, buf: Float32Array<ArrayBuffer>): number {
  analyser.getFloatTimeDomainData(buf);
  let sum = 0;
  for (let i = 0; i < buf.length; i++) sum += buf[i] * buf[i];
  const db = 20 * Math.log10(Math.sqrt(sum / buf.length) || 1e-9);
  return Math.min(1, Math.max(0, (db + 60) / 50));
}
