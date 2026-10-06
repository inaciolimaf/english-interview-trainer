"""Grapheme-to-phoneme via the espeak-ng CLI (en-us).

Output uses the same IPA inventory as the wav2vec2 espeak phoneme model:
phones separated by spaces, words separated by " | ", stress marks removed.
Spec 04 may switch to ``phonemizer`` (same espeak backend) with per-word caching.
"""

import shutil
import subprocess
from functools import lru_cache

STRESS_MARKS = str.maketrans("", "", "ˈˌ")
WORD_SEP = " | "


@lru_cache(maxsize=4096)
def espeak_phonemes(text: str, voice: str = "en-us") -> str:
    exe = shutil.which("espeak-ng")
    if exe is None:
        raise RuntimeError("espeak-ng not found — install it (e.g. `sudo apt install espeak-ng`)")
    out = subprocess.run(
        [exe, "-q", "--ipa", "--sep= ", "-v", voice, text],
        capture_output=True, text=True, check=True,
    ).stdout
    # espeak separates words with a double space (phone sep + word space)
    words = []
    for line in out.splitlines():
        for word in line.translate(STRESS_MARKS).split("  "):
            if phones := " ".join(word.split()):
                words.append(phones)
    return WORD_SEP.join(words)
