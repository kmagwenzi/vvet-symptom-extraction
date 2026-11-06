"""Escalation is a rule, so it is tested like one."""

from __future__ import annotations

import pytest

from app.escalate import decide_escalation
from app.signs import CRITICAL_SIGN_IDS, SIGN_IDS
from tests.conftest import finding

NON_CRITICAL = [s for s in SIGN_IDS if s not in CRITICAL_SIGN_IDS]


@pytest.mark.parametrize("sign_id", sorted(CRITICAL_SIGN_IDS))
@pytest.mark.parametrize("value", ["yes", "not_sure"])
def test_critical_sign_escalates_on_yes_and_not_sure(sign_id, value):
    escalate, reason = decide_escalation([finding(sign_id, value, "quote")])
    assert escalate is True
    assert sign_id in reason
    assert value in reason


@pytest.mark.parametrize("sign_id", sorted(CRITICAL_SIGN_IDS))
def test_critical_sign_does_not_escalate_when_negated(sign_id):
    escalate, reason = decide_escalation([finding(sign_id, "no", "quote")])
    assert escalate is False
    assert "No escalation" in reason


@pytest.mark.parametrize("sign_id", NON_CRITICAL)
def test_non_critical_sign_never_escalates(sign_id):
    escalate, _ = decide_escalation([finding(sign_id, "yes", "quote")])
    assert escalate is False


def test_no_findings_does_not_escalate_and_says_so():
    escalate, reason = decide_escalation([])
    assert escalate is False
    assert "no signs" in reason.lower()
    for sign_id in CRITICAL_SIGN_IDS:
        assert sign_id in reason


def test_escalation_lists_every_critical_hit():
    findings = [
        finding("froth_nose_mouth", "yes", "foam"),
        finding("unable_to_stand", "not_sure", "maybe she cannot stand"),
        finding("ticks", "yes", "ticks"),
    ]
    escalate, reason = decide_escalation(findings)
    assert escalate is True
    assert "froth_nose_mouth=yes" in reason
    assert "unable_to_stand=not_sure" in reason
    assert "ticks" not in reason
