// Copies the Silero VAD model, its AudioWorklet and the onnxruntime-web WASM files to
// public/vad/ so @ricky0123/vad-web can load them from /vad/ (dev and build).
import { copyFileSync, mkdirSync, readdirSync } from "node:fs";
import { join } from "node:path";

const out = "public/vad";
mkdirSync(out, { recursive: true });

const sources = [
  ["node_modules/@ricky0123/vad-web/dist", (f) => f.endsWith(".onnx") || /^vad\.worklet.*\.js$/.test(f)],
  ["node_modules/onnxruntime-web/dist", (f) => /^ort-wasm.*\.(wasm|mjs)$/.test(f)],
];

let copied = 0;
for (const [dir, keep] of sources) {
  for (const file of readdirSync(dir).filter(keep)) {
    copyFileSync(join(dir, file), join(out, file));
    copied++;
  }
}
console.log(`copied ${copied} VAD asset(s) to ${out}`);
