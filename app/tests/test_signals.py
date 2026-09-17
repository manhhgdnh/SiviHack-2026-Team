"""Deterministic evidence computed before call 2: vague phrases, money, dates/durations."""

from pathlib import Path

from app.signals import compute_signals, render_signals
from app.splitter import parse

SAMPLES = Path(__file__).resolve().parents[2] / "sample_data"
WEAK = parse((SAMPLES / "response_1_weak.md").read_text())
OVER = parse((SAMPLES / "response_4_overpromise.md").read_text())
STRONG = parse((SAMPLES / "response_3_strong.md").read_text())


def test_weak_proposal_has_vague_phrases_and_no_numbers_in_pricing_or_timeline():
    sig = compute_signals(WEAK)
    phrases = {v.phrase for v in sig.vaguePhrases}
    assert "upon further discussion" in phrases and "in a timely manner" in phrases
    hit = next(v for v in sig.vaguePhrases if v.phrase == "upon further discussion")
    assert hit.section == "§6" and "Pricing will be provided" in hit.context
    assert sig.pricing.sections == ["§6"] and sig.pricing.mentions == []
    assert sig.timeline.sections == ["§5"] and sig.timeline.mentions == []


def test_overpromise_has_money_and_duration_mentions_tagged_by_section():
    sig = compute_signals(OVER)
    assert sig.pricing.sections == ["§4"]
    assert [(m.value, m.section) for m in sig.pricing.mentions] == [("€98,000", "§4")]
    assert sig.timeline.sections == ["§3"]
    assert ("8 weeks", "§3") in [(m.value, m.section) for m in sig.timeline.mentions]
    assert ("weeks in advance", "§2") not in [(m.value, m.section) for m in sig.timeline.mentions]


def test_strong_proposal_is_dense_with_evidence():
    sig = compute_signals(STRONG)
    assert len(sig.pricing.mentions) >= 4
    assert len(sig.timeline.mentions) >= 3
    assert all(v.phrase not in {"tbd", "asap", "on request"} for v in sig.vaguePhrases)


def test_phrase_matching_is_case_insensitive_and_whole_word():
    doc = parse("## Terms\nPricing: TBD. Delivery ASAP, details to be discussed. Not a tbdx.")
    sig = compute_signals(doc)
    assert [v.phrase for v in sig.vaguePhrases] == ["tbd", "asap", "to be discussed"]


def test_render_is_compact_and_names_sections():
    text = render_signals(compute_signals(OVER), OVER)
    assert "§4 Pricing" in text and "€98,000" in text
    assert "§3 Timeline" in text and "8 weeks" in text
    assert "none" in render_signals(compute_signals(parse("## A\nhello")), parse("## A\nhello"))
