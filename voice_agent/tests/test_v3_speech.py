"""eleven_v3 audio-tag helpers (no API required)."""

from agent.main import _prepare_v3_text


def test_maps_mild_tags_and_adds_excited_beat():
    out = _prepare_v3_text(
        "[friendly] I'd be happy to help you book a table! "
        "[friendly] What day are you looking for? "
        "[happy] We're open on August 14th."
    )
    assert out == (
        "[excited] Oh! I'd be happy to help you book a table! "
        "What day are you looking for? We're open on August 14th."
    )


def test_keeps_distinct_official_tags_with_beats():
    out = _prepare_v3_text("[curious] Which day works? [excited] Saturday at seven is open.")
    assert out == (
        "[curious] Hmm — Which day works? [excited] Saturday at seven is open."
    )


def test_lowercases_and_maps_warm():
    assert _prepare_v3_text("[Warm] Thanks for calling.") == "[excited] Oh! Thanks for calling."


def test_adds_default_tag_when_missing():
    assert _prepare_v3_text("Thanks for calling.") == "[excited] Oh! Thanks for calling."


def test_does_not_double_oh():
    assert _prepare_v3_text("[excited] Oh! Thanks for calling.") == (
        "[excited] Oh! Thanks for calling."
    )
