"""The two extractors.

LLMExtractor is the implementation the task asks for: the model reads the
message, this module validates what it says.

RuleExtractor is a keyword baseline. It exists for two reasons: the repo runs
and its tests pass with no network and no key, and a baseline is how you find
out whether the model is actually earning its place.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Protocol

from app.llm import LLMClient
from app.prompt import build_messages
from app.schema import Finding, SignID, SignValue
from app.signs import CRITICAL_SIGN_IDS, SIGN_IDS
from app.validate import UNCERTAINTY_CUES, clean_findings, findings_from_model, normalise


@dataclass
class ExtractionResult:
    findings: list[Finding] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)
    repaired: list[str] = field(default_factory=list)
    mode: str = "llm"


class Extractor(Protocol):
    name: str

    def extract(self, message: str) -> ExtractionResult: ...


class LLMExtractor:
    name = "llm"

    def __init__(self, client: LLMClient | None = None) -> None:
        self.client = client or LLMClient.from_env()

    def extract(self, message: str) -> ExtractionResult:
        system, user = build_messages(message)
        raw = self.client.complete(system, user)
        cleaned = findings_from_model(raw, message)
        return ExtractionResult(
            findings=cleaned.findings,
            dropped=cleaned.dropped,
            repaired=cleaned.repaired,
            mode=self.name,
        )


# --------------------------------------------------------------------------
# Offline baseline
# --------------------------------------------------------------------------

_PATTERNS: dict[str, tuple[str, ...]] = {
    "reduced_appetite": (
        r"not (?:been )?eating",
        r"isn'?t eating",
        r"stopped eating",
        r"no appetite",
        r"eating less",
        r"not grazing",
        r"off (?:her|his|its) food",
        r"haisi kudya",
        r"haasi kudya",
        r"haadyi",
    ),
    "weakness": (
        r"weak",
        r"dull",
        r"lethargic",
        r"tired",
        r"lying down",
        r"down all day",
    ),
    "swelling": (
        r"swell(?:ing|en)?",
        r"lump",
        r"mbandabvu",
        r"under the jaw",
        r"below the ear",
        r"in front of the shoulder",
    ),
    "rapid_breathing": (
        r"breathing\s+(?:\w+\s+){0,2}(?:fast|heavily|hard|quickly)",
        r"panting",
        r"short of breath",
        r"breathes fast",
    ),
    "cloudy_eye": (
        r"cloudy",
        r"milky",
        r"white eye",
        r"grey eye",
        r"gray eye",
        r"eye looks white",
        r"ziso",
    ),
    "froth_nose_mouth": (
        r"foam",
        r"froth",
        r"saliva",
        r"spit",
    ),
    "red_urine": (
        r"red urine",
        r"dark urine",
        r"brown urine",
        r"urine is (?:red|brown|dark)",
        r"colour of (?:strong )?tea",
        r"color of (?:strong )?tea",
        r"urine (?:yakasviba|tema)",
    ),
    "unable_to_stand": (
        r"can'?t get up",
        r"cannot get up",
        r"can'?t stand",
        r"cannot stand",
        r"unable to stand",
        r"won'?t stand",
        r"haagone kumira",
    ),
    "ticks": (r"ticks?", r"zigomara"),
}

_NEGATION = re.compile(
    r"\b(no|not|without|none|never|negative for|free of|hapana|pasina)\b", re.IGNORECASE
)
_TERMINATORS = ".!?\n"


def _sentence_around(text: str, start: int, end: int) -> tuple[int, str]:
    """Return (offset_of_window_in_text, sentence_text)."""
    left = 0
    for i in range(start - 1, -1, -1):
        if text[i] in _TERMINATORS:
            left = i + 1
            break
    right = len(text)
    for i in range(end, len(text)):
        if text[i] in _TERMINATORS:
            right = i + 1
            break
    return left, text[left:right].strip()


def _hedged(window: str) -> bool:
    lowered = normalise(window)
    return any(cue in lowered for cue in UNCERTAINTY_CUES)


# A clause boundary stops a negation from reaching across it. "No foam from
# the nose but she cannot stand." must not let "No" cancel "cannot stand" —
# "but" is a wall, not a window. Comma and semicolon are walls too.
_CLAUSE_BOUNDARY = re.compile(
    r"[,;]|(?<![a-z])(?:although|though|however|but)(?![a-z])", re.IGNORECASE
)


def _negated(window: str, rel: int) -> bool:
    """True when a negation word sits between the nearest clause boundary and the match.

    Only text before the match counts, and only within its own clause, so
    "not eating" stays a positive finding for reduced_appetite while a "no" in
    an earlier clause cannot cancel a later one.
    """
    before = window[:rel]
    boundaries = [m.end() for m in _CLAUSE_BOUNDARY.finditer(before)]
    start = boundaries[-1] if boundaries else 0
    return bool(_NEGATION.search(before[start:]))


class RuleExtractor:
    name = "rule"

    def extract(self, message: str) -> ExtractionResult:
        best: dict[str, Finding] = {}
        severity = {"yes": 3, "not_sure": 2, "no": 1}

        for sign_id, patterns in _PATTERNS.items():
            for pattern in patterns:
                for match in re.finditer(pattern, message, re.IGNORECASE):
                    win_start, window = _sentence_around(
                        message, match.start(), match.end()
                    )
                    rel = match.start() - win_start
                    value = "yes"
                    if _hedged(window):
                        value = "not_sure"
                    elif _negated(window, rel):
                        value = "no"
                    if value == "no" and sign_id in CRITICAL_SIGN_IDS:
                        # A regex baseline must never cancel an alarm. A critical
                        # sign that only looks negated becomes not_sure, so the
                        # cheap mistake is a needless call, not a dead animal.
                        value = "not_sure"
                    finding = Finding(
                        sign_id=SignID(sign_id), value=SignValue(value), quote=window
                    )
                    current = best.get(sign_id)
                    if current is None or severity[value] > severity[current.value.value]:
                        best[sign_id] = finding

        ordered = [best[s] for s in SIGN_IDS if s in best]
        return ExtractionResult(findings=ordered, mode=self.name)


def _dedupe(notes: list[str]) -> list[str]:
    seen: dict[str, None] = {}
    for note in notes:
        seen.setdefault(note, None)
    return list(seen)


def enforce_contract(result: ExtractionResult, message: str) -> ExtractionResult:
    """Re-validate at the boundary, whatever the extractor returned.

    Defence in depth: the LLM extractor validates its own output, and this runs
    the same checks again on the way out. The response contract (only the nine
    sign ids, only grounded quotes, yes/no/not_sure) therefore holds for every
    extractor, including a future one nobody has written yet.
    """
    cleaned = clean_findings(
        [f.model_dump(mode="json") for f in result.findings], message
    )
    return ExtractionResult(
        findings=cleaned.findings,
        dropped=_dedupe([*result.dropped, *cleaned.dropped]),
        repaired=_dedupe([*result.repaired, *cleaned.repaired]),
        mode=result.mode,
    )


def get_extractor() -> Extractor:
    """Choose an extractor from the environment.

    EXTRACTOR=llm  -> the model (requires LLM_API_KEY)
    EXTRACTOR=rule -> the offline baseline
    EXTRACTOR=auto -> the model when a key is present, otherwise the baseline
    """
    choice = os.getenv("EXTRACTOR", "auto").strip().lower()
    if choice == "rule":
        return RuleExtractor()
    if choice == "llm":
        return LLMExtractor()
    if choice == "auto":
        return LLMExtractor() if os.getenv("LLM_API_KEY") else RuleExtractor()
    raise ValueError(f"EXTRACTOR must be llm, rule or auto (got {choice!r})")
