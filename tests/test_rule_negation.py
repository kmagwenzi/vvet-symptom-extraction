"""Regression: the rule extractor must not let negation bleed across clauses.

Exposed by review: "No foam from the nose but she cannot stand." returned
unable_to_stand = no because the lookback window crossed the "but" and read the
"No". The fix bounds negation to its own clause, and a second guard never lets
the rule path emit "no" on a critical sign.
"""

from __future__ import annotations

from app.escalate import decide_escalation
from app.extract import RuleExtractor


def values(result):
    return {f.sign_id.value: f.value.value for f in result.findings}


def test_negation_does_not_bleed_across_a_conjunction():
    # The exact sentence that exposed the bug.
    r = RuleExtractor().extract("No foam from the nose but she cannot stand.")
    assert values(r)["unable_to_stand"] == "yes"
    escalate, _ = decide_escalation(r.findings)
    assert escalate is True


def test_negation_stops_at_a_comma():
    r = RuleExtractor().extract("No ticks, she cannot get up.")
    assert values(r)["unable_to_stand"] == "yes"


def test_rule_extractor_never_cancels_a_critical_alarm():
    # Even correctly negated, a critical sign is not_sure, never "no".
    r = RuleExtractor().extract("There is no foam from her mouth.")
    assert values(r)["froth_nose_mouth"] == "not_sure"
    escalate, _ = decide_escalation(r.findings)
    assert escalate is True


def test_negation_within_its_own_clause_still_negates_non_critical():
    r = RuleExtractor().extract("She is not weak and can stand fine.")
    assert values(r).get("weakness") == "no"


def test_negation_stops_at_and():
    # "Not eating" is a positive finding for reduced_appetite; the "and" must
    # stop that "Not" reaching the breathing clause.
    r = RuleExtractor().extract("Not eating and breathing fast.")
    v = values(r)
    assert v["reduced_appetite"] == "yes"
    assert v["rapid_breathing"] == "yes"


def test_explicit_negation_on_a_critical_sign_escalates_on_purpose():
    """The documented cost of the safety net, pinned so it cannot drift.

    A regex cannot tell "no foam" (reassuring) from a mis-parsed clause, so the
    rule path reports not_sure rather than no on the three critical signs. That
    is a false alarm on a healthy animal, accepted deliberately.
    """
    r = RuleExtractor().extract("No foam, no cloudy eyes, she is just off her food.")
    v = values(r)
    assert v["froth_nose_mouth"] == "not_sure"
    assert v["cloudy_eye"] == "not_sure"
    escalate, _ = decide_escalation(r.findings)
    assert escalate is True
