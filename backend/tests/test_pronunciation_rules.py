from api.pronunciation.align import align, distance
from api.pronunciation.rules import Calibration, Context, Stats, Variants, judge_word, threshold

CAL = Calibration({"θ": Stats(3.0, 1.5), "ʊ": Stats(0.0, 3.0)}, fallback=Stats(3.0, 1.0))


def result(phones: list[tuple[str, float, str]], heard: list[str]) -> dict:
    return {"aligned": True, "start_ms": 100, "end_ms": 600, "heard": heard,
            "phones": [{"p": p, "score": s, "competitor": c} for p, s, c in phones]}


THROUGHPUT_BAD = result(
    [("θ", -6.7, "t"), ("ɹ", 4.7, "w"), ("uː", 3.5, "ʊ"), ("p", 5.0, "b"), ("ʊ", -3.4, "ʌ"), ("t", 3.0, "d")],
    ["t", "ɹ", "uː", "p", "ʌ", "t"],
)


def ctx(**kw) -> Context:
    return Context(**{"calibration": CAL, "variants": Variants(), **kw})


def test_align_ops():
    ops = [(e.op, e.expected, e.heard) for e in align(["s", "t", "æ", "k"], ["ɪ", "s", "t", "æ", "k"])]
    assert ops[0] == ("ins", None, "ɪ")
    assert distance(["θ", "ɪ", "ŋ", "k"], ["t", "ɪ", "ŋ", "k"]) == 1


def test_substitution_below_threshold_is_an_error():
    cands = judge_word(ctx(), "throughput", 3, THROUGHPUT_BAD)
    theta = [c for c in cands if c.phone == "θ"]
    assert len(theta) == 1
    c = theta[0]
    assert c.category == "pron:phoneme:θ" and c.heard_phone == "t" and c.threshold == 0.0
    # ʊ: native mean 0, std 3 → threshold -6; -3.4 is within native range
    assert not any(c.phone == "ʊ" for c in cands)


def test_threshold_uses_k_offsets_and_tech_terms():
    c = ctx(k=2.0)
    assert threshold(c, "θ", "think") == 0.0
    c.offsets[("θ", None)] = 1.0
    assert threshold(c, "θ", "think") == -1.0
    c.offsets[("θ", "think")] = 2.0  # word-specific adjustment adds up
    assert threshold(c, "θ", "think") == -3.0
    c.tech_terms.add("throughput")
    assert threshold(c, "θ", "throughput") == 3.0 - 1.5 * 1.5 - 1.0  # stricter k, phoneme offset


def test_user_offset_makes_it_tolerant():
    c = ctx(offsets={("θ", "throughput"): 7.0})
    assert not any(x.phone == "θ" for x in judge_word(c, "throughput", 0, THROUGHPUT_BAD))


def test_general_variant_is_not_an_error():
    c = ctx(variants=Variants(general={("θ", "t")}))
    assert not any(x.phone == "θ" for x in judge_word(c, "throughput", 0, THROUGHPUT_BAD))


def test_word_variant_is_not_an_error():
    data = result([("d", 4.0, "t"), ("eɪ", -5.0, "æ"), ("ɾ", 3.0, "t"), ("ə", 2.0, "ɐ")], ["d", "æ", "ɾ", "ə"])
    assert judge_word(ctx(), "data", 0, data)  # without the variant: flagged
    c = ctx(variants=Variants(by_word={"data": [["d", "æ", "ɾ", "ə"]]}))
    assert judge_word(c, "data", 0, data) == []


def test_function_words_and_unaligned_words_are_skipped():
    assert judge_word(ctx(), "the", 0, result([("ð", -9.0, "d"), ("ə", 1.0, "ɐ")], ["d", "ə"])) == []
    assert judge_word(ctx(), "think", 0, {"aligned": False, "phones": [], "heard": []}) == []


def test_initial_epenthesis():
    data = result([("s", 5.0, "z"), ("t", 5.0, "d"), ("æ", 2.0, "ɛ"), ("k", 5.0, "ɡ")], ["i", "s", "t", "æ", "k"])
    cands = judge_word(ctx(), "stack", 0, data)
    assert [c.category for c in cands] == ["pron:epenthesis"] and cands[0].heard_phone == "i"


def test_final_epenthesis_unless_next_word_starts_with_vowel():
    data = result([("ɡ", 5.0, "k"), ("uː", 3.0, "ʊ"), ("ɡ", 5.0, "k"), ("əl", 3.0, "l")], ["ɡ", "uː", "ɡ", "əl", "i"])
    assert [c.category for c in judge_word(ctx(), "google", 0, data)] == ["pron:epenthesis"]
    assert judge_word(ctx(), "google", 0, data, next_word_phones=["ɪ", "z"]) == []


def test_final_ed_as_syllable():
    data = result([("j", 5.0, "i"), ("uː", 3.0, "ʊ"), ("z", 4.0, "s"), ("d", 3.0, "t")], ["j", "uː", "z", "ɪ", "d"])
    assert [c.category for c in judge_word(ctx(), "used", 0, data)] == ["pron:final_ed"]


def test_vowel_pair_category():
    data = result([("ʃ", 5.0, "s"), ("ɪ", -4.0, "iː"), ("p", 5.0, "b")], ["ʃ", "iː", "p"])
    assert [c.category for c in judge_word(ctx(), "ship", 0, data)] == ["pron:vowel:ɪ-iː"]


def test_low_score_without_substitution_uses_competitor():
    data = result([("θ", -6.0, "f"), ("ɪ", 3.0, "i"), ("ŋ", 4.0, "n"), ("k", 5.0, "ɡ")], ["θ", "ɪ", "ŋ", "k"])
    (c,) = judge_word(ctx(), "think", 0, data)
    assert c.heard_phone == "f"
