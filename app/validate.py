"""Validation of whatever the model returned.

The model is untrusted output. Four checks run, in this order:

1. Parse: find the JSON object in the answer, tolerate fences and prose.
2. Shape: sign_id must be in the fixed list, value must be in the enum.
3. Ground: the quote must actually appear in the message.
4. Repair: an ungrounded quote on a *critical* sign is not deleted - it becomes
   not_sure. Deleting it would quietly remove the one finding that could
   escalate a case, and silence is the expensive failure mode in triage.

Duplicates collapse to the strongest claim (yes > not_sure > no), and a "yes"
whose quote hedges is downgraded to not_sure. Both rules only ever move a
finding toward caution, never away from it.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from app.schema import Finding, SignID, SignValue
from app.signs import CRITICAL_SIGN_IDS, SIGN_IDS, SIGN_ID_SET

UNCERTAINTY_CUES: tuple[str, ...] = (
    "not sure",
    "unsure",
    "not certain",
    "i think",
    "i guess",
    "maybe",
    "perhaps",
    "possibly",
    "might be",
    "seems",
    "looks like",
    "i suspect",
    "ndinofunga",
    "pamwe",
)

_SEVERITY = {"yes": 3, "not_sure": 2, "no": 1}

_FENCE = re.compile(r"^\s*```(?:json)?|\s*```\s*$", re.IGNORECASE)


class ExtractionError(ValueError):
    """The model's answer could not be turned into findings at all."""


@dataclass
class CleanResult:
    findings: list[Finding]
    dropped: list[str]
    repaired: list[str]


def normalise(text: str) -> str:
    """Lowercase, unify quotes, collapse whitespace. Used for grounding only."""
    text = text.replace("\u2019", "'").replace("\u2018", "'")
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    text = re.sub(r"\s+", " ", text)
    return text.strip().lower()


def is_grounded(quote: str, message: str) -> bool:
    """True when the quote really is a slice of the message.

    A paraphrased or translated quote fails on purpose: the quote is the
    evidence a clinician reads, so it has to be the farmer's own words.
    """
    quote_n = normalise(quote).strip(" .,;:!?\"'")
    if not quote_n:
        return False
    return quote_n in normalise(message)


def parse_model_json(raw: str) -> dict:
    """Pull the JSON object out of a model answer that may be fenced or chatty."""
    text = _FENCE.sub("", (raw or "").strip())
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ExtractionError("no JSON object found in the model answer")
    try:
        payload = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ExtractionError(f"model answer is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ExtractionError("model answer is not a JSON object")
    return payload


def _has_uncertainty_cue(text: str) -> bool:
    lowered = normalise(text)
    return any(cue in lowered for cue in UNCERTAINTY_CUES)


def clean_findings(raw_findings: object, message: str) -> CleanResult:
    """Validate, ground and repair the model's findings."""
    if raw_findings is None:
        raise ExtractionError("model answer has no 'findings' key")
    if not isinstance(raw_findings, list):
        raise ExtractionError("'findings' is not a list")

    dropped: list[str] = []
    repaired: list[str] = []
    best: dict[str, Finding] = {}

    for item in raw_findings:
        if not isinstance(item, dict):
            dropped.append("non-object finding")
            continue

        raw_sign = item.get("sign_id", "")
        sign_id = str(getattr(raw_sign, "value", raw_sign)).strip()
        if sign_id not in SIGN_ID_SET:
            dropped.append(f"unknown sign_id {sign_id!r}")
            continue

        raw_value = item.get("value", "")
        value = str(getattr(raw_value, "value", raw_value)).strip().lower()
        if value not in _SEVERITY:
            dropped.append(f"invalid value {value!r} for {sign_id}")
            continue

        quote = str(item.get("quote", "")).strip()

        if not is_grounded(quote, message):
            if sign_id in CRITICAL_SIGN_IDS:
                # Fail toward triage: never delete the finding that could
                # escalate a case. Keep it, but claim only what is certain.
                quote = quote or message.strip()
                value = "not_sure"
                repaired.append(f"{sign_id} kept as not_sure (quote not grounded)")
            else:
                dropped.append(f"{sign_id} dropped (quote not in message)")
                continue

        if value == "yes" and _has_uncertainty_cue(quote):
            value = "not_sure"
            repaired.append(f"{sign_id} downgraded to not_sure (hedged quote)")

        finding = Finding(
            sign_id=SignID(sign_id), value=SignValue(value), quote=quote
        )
        current = best.get(sign_id)
        if current is None or _SEVERITY[value] > _SEVERITY[current.value.value]:
            best[sign_id] = finding

    ordered = [best[s_id] for s_id in SIGN_IDS if s_id in best]
    return CleanResult(findings=ordered, dropped=dropped, repaired=repaired)


def findings_from_model(raw: str, message: str) -> CleanResult:
    """Full path from a raw model answer to clean findings."""
    payload = parse_model_json(raw)
    return clean_findings(payload.get("findings"), message)
