"""Escalation, decided in plain code.

The model never decides escalation. It reports findings; this module applies a
rule that can be read, reviewed and tested without knowing anything about
language models.
"""

from __future__ import annotations

from app.schema import Finding
from app.signs import SIGNS, critical_list


def decide_escalation(findings: list[Finding]) -> tuple[bool, str]:
    """Return (escalate, reason).

    A case escalates when a critical sign is reported as yes or not_sure.
    not_sure escalates on purpose: a farmer who is unsure about froth, a cloudy
    eye, or an animal that cannot stand is still describing an emergency, and
    the cheap mistake is a needless call, not a dead animal.
    """
    hits = [
        f
        for f in findings
        if any(s.sign_id == f.sign_id.value and s.critical for s in SIGNS)
        and f.value.value in {"yes", "not_sure"}
    ]

    if hits:
        detail = ", ".join(f"{f.sign_id.value}={f.value.value}" for f in hits)
        return True, f"Escalate: critical sign reported ({detail})."

    if not findings:
        return False, (
            "No escalation: no signs were extracted from this message "
            f"(escalation requires one of {critical_list()})."
        )

    found = ", ".join(f"{f.sign_id.value}={f.value.value}" for f in findings)
    return False, (
        f"No escalation: none of {critical_list()} reported as yes or not_sure "
        f"(findings: {found})."
    )
