import pytest

from api.realtime.turn_policy import (
    Decision, TurnPolicy, decide_end_of_turn, is_backchannel, is_incomplete, is_substantive,
)

P = TurnPolicy()


@pytest.mark.parametrize("text", [
    "and then", "So I would use", "we could put it in the", "Hmm, the main thing is,",
    "I think...", "because", "so we'd shard", "Let me think about the uh",
])
def test_incomplete(text):
    assert is_incomplete(text)


@pytest.mark.parametrize("text", [
    "I would use Redis.", "That's it.", "We shard by user id", "Let me think.", "",
])
def test_complete(text):
    assert not is_incomplete(text)


def test_confident_model_ends_early():
    assert decide_end_of_turn(P, 650, 0.9, "I would use Redis.") == Decision.END


def test_unsure_model_waits_for_silence_threshold():
    assert decide_end_of_turn(P, 700, 0.6, "I would use Redis.") == Decision.WAIT
    assert decide_end_of_turn(P, 1500, 0.6, "I would use Redis.") == Decision.END


def test_low_probability_waits_until_max():
    assert decide_end_of_turn(P, 3000, 0.1, "I would use Redis.") == Decision.WAIT
    assert decide_end_of_turn(P, 3000, 0.3, "I would use Redis") == Decision.WAIT  # no final mark
    assert decide_end_of_turn(P, 4000, 0.1, "I would use Redis.") == Decision.END


def test_incomplete_phrase_never_ends_before_max():
    for silence in (600, 1000, 2000, 3900):
        assert decide_end_of_turn(P, silence, 0.99, "so I would use") == Decision.WAIT
    assert decide_end_of_turn(P, 4000, 0.99, "so I would use") == Decision.END


def test_nothing_before_check_after():
    assert decide_end_of_turn(P, 300, 0.99, "Done.") == Decision.WAIT


def test_detector_unavailable_falls_back_to_silence():
    assert decide_end_of_turn(P, 1000, None, "Done.") == Decision.WAIT
    assert decide_end_of_turn(P, 1500, None, "Done.") == Decision.END


@pytest.mark.parametrize("text", ["Yeah.", "uh-huh", "Okay, okay.", "Mm-hmm.", "Got it.", "Right, right", ""])
def test_backchannel(text):
    assert is_backchannel(text)


@pytest.mark.parametrize("text", ["Yeah, but what about writes?", "Sorry, can you repeat?", "Okay so I would"])
def test_not_backchannel(text):
    assert not is_backchannel(text)


@pytest.mark.parametrize("text", ["E.H.", "Uh-huh, yeah", "", "Okay okay", "Mammal."])
def test_not_substantive_yet(text):
    assert not is_substantive(text)


@pytest.mark.parametrize("text", ["Sorry, can", "Wait, I think", "Yeah but", "Sorry.", "Wait"])
def test_substantive(text):
    assert is_substantive(text)


def test_punctuated_sentence_needs_only_a_weak_model_vote():
    assert decide_end_of_turn(P, 1500, 0.26, "And that's it.") == Decision.END
    assert decide_end_of_turn(P, 1000, 0.26, "And that's it.") == Decision.WAIT  # not before silence_ms
    assert decide_end_of_turn(P, 1500, 0.26, "And that's it") == Decision.WAIT  # no final mark
    assert decide_end_of_turn(P, 1500, 0.10, "And that's it.") == Decision.WAIT  # model says no
    assert decide_end_of_turn(P, 1500, 0.9, "so I would use.") == Decision.WAIT  # still incomplete
