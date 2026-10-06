import shutil

import pytest

from api.pronunciation.g2p import espeak_phonemes

pytestmark = pytest.mark.skipif(shutil.which("espeak-ng") is None, reason="espeak-ng missing")


def test_single_word_has_no_stress_marks():
    assert espeak_phonemes("throughput") == "θ ɹ uː p ʊ t"


def test_words_are_separated():
    assert espeak_phonemes("the cache") == "ð ə | k æ ʃ"
