let current: HTMLAudioElement | null = null;

/** Play an error clip; starting another one stops the previous. */
export function playClip(url: string): void {
  current?.pause();
  current = new Audio(url);
  void current.play();
}
