import { api } from "../api/client";

const MAX_CHUNK = 450; // /api/speech/tts accepts up to 600 chars

let queue: HTMLAudioElement[] = [];
let generation = 0;

/** Text without the coach's markers and markdown, as it should sound. */
export function speakable(text: string): string {
  return text
    .replace(/\[\[clip:[^\]]+\]\]/g, "")
    .replace(/\[\[say:([^\]]+)\]\]/g, "$1")
    .replace(/\*+/g, "")
    .replace(/^\s*-\s+/gm, "")
    .replace(/\s+/g, " ")
    .trim();
}

function chunks(text: string): string[] {
  const sentences = text.match(/[^.!?]+[.!?]+["')\]]*\s*|[^.!?]+$/g) ?? [text];
  const out: string[] = [];
  let current = "";
  for (const s of sentences) {
    if ((current + s).length > MAX_CHUNK && current) {
      out.push(current.trim());
      current = "";
    }
    current += s;
  }
  if (current.trim()) out.push(current.trim());
  return out.flatMap((c) => (c.length > MAX_CHUNK ? c.match(new RegExp(`.{1,${MAX_CHUNK}}(\\s|$)`, "g")) ?? [c] : [c]));
}

export function stopSpeaking(): void {
  generation++;
  for (const a of queue) a.pause();
  queue = [];
}

/** Read text aloud with the interviewer's voice, chunk by chunk (synthesis overlaps playback). */
export async function speak(text: string): Promise<void> {
  stopSpeaking();
  const mine = generation;
  const parts = chunks(speakable(text));
  const audios = parts.map((p) => api.speak(p).then((blob) => new Audio(URL.createObjectURL(blob))));
  for (const pending of audios) {
    let audio: HTMLAudioElement;
    try {
      audio = await pending;
    } catch {
      return;
    }
    if (mine !== generation) return;
    queue.push(audio);
    await new Promise<void>((resolve) => {
      audio.onended = () => resolve();
      audio.onpause = () => resolve();
      void audio.play().catch(() => resolve());
    });
    if (mine !== generation) return;
  }
}
