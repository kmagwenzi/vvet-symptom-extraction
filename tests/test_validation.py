"""What happens to a bad or dishonest model answer."""

from __future__ import annotations

import pytest

from app.validate import (
    ExtractionError,
    clean_findings,
    findings_from_model,
    is_grounded,
    parse_model_json,
)

MESSAGE = (
    "There's foam coming from her nose and she can't get up. "
    "She also has mbandabvu under the ear."
)


def test_parses_fenced_json_with_prose_around_it():
    raw = 'Sure, here you go:\n\n```json\n{"findings": []}\n```\nThanks!'
    assert parse_model_json(raw) == {"findings": []}


def test_rejects_an_answer_with_no_json():
    with pytest.raises(ExtractionError):
        parse_model_json("I could not extract anything from this message.")


def test_rejects_malformed_json():
    with pytest.raises(ExtractionError):
        parse_model_json('{"findings": [}')


def test_unknown_sign_id_is_dropped():
    result = clean_findings(
        [{"sign_id": "broken_leg", "value": "yes", "quote": "can't get up"}], MESSAGE
    )
    assert result.findings == []
    assert any("unknown sign_id" in note for note in result.dropped)


def test_invalid_value_is_dropped():
    result = clean_findings(
        [{"sign_id": "ticks", "value": "maybe", "quote": "foam"}], MESSAGE
    )
    assert result.findings == []


def test_quote_must_appear_in_the_message():
    assert is_grounded("foam coming from her nose", MESSAGE)
    assert not is_grounded("she has a high fever", MESSAGE)


def test_ungrounded_non_critical_finding_is_dropped():
    result = clean_findings(
        [{"sign_id": "ticks", "value": "yes", "quote": "covered in ticks"}], MESSAGE
    )
    assert result.findings == []
    assert any("dropped" in note for note in result.dropped)


def test_ungrounded_critical_finding_survives_as_not_sure():
    """Fail toward triage: never delete the finding that could escalate."""
    result = clean_findings(
        [{"sign_id": "froth_nose_mouth", "value": "yes", "quote": "frothing badly"}],
        "The cow is off her food.",
    )
    assert len(result.findings) == 1
    assert result.findings[0].value.value == "not_sure"
    assert any("not grounded" in note for note in result.repaired)


def test_hedged_yes_is_downgraded_to_not_sure():
    message = "I think her eye looks cloudy but I'm not sure."
    result = clean_findings(
        [{"sign_id": "cloudy_eye", "value": "yes", "quote": message}], message
    )
    assert result.findings[0].value.value == "not_sure"


def test_duplicates_collapse_to_the_strongest_claim():
    result = clean_findings(
        [
            {"sign_id": "froth_nose_mouth", "value": "not_sure", "quote": "foam"},
            {"sign_id": "froth_nose_mouth", "value": "yes", "quote": "foam"},
        ],
        MESSAGE,
    )
    assert len(result.findings) == 1
    assert result.findings[0].value.value == "yes"


def test_findings_come_back_in_the_canonical_sign_order():
    result = clean_findings(
        [
            {"sign_id": "froth_nose_mouth", "value": "yes", "quote": "foam"},
            {"sign_id": "swelling", "value": "yes", "quote": "mbandabvu under the ear"},
        ],
        MESSAGE,
    )
    assert [f.sign_id.value for f in result.findings] == ["swelling", "froth_nose_mouth"]


def test_missing_findings_key_raises():
    with pytest.raises(ExtractionError):
        clean_findings(None, MESSAGE)


def test_full_path_from_raw_answer():
    raw = (
        '{"findings": [{"sign_id": "froth_nose_mouth", "value": "yes", '
        '"quote": "foam coming from her nose"}]}'
    )
    result = findings_from_model(raw, MESSAGE)
    assert [f.sign_id.value for f in result.findings] == ["froth_nose_mouth"]
