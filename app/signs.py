"""The fixed list of signs.

This module is the single source of truth. The prompt, the validator and the
tests all read from here, so a new sign is one edit and cannot drift between
the instruction given to the model and the check applied to its answer.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Sign:
    sign_id: str
    meaning: str
    #: A critical sign escalates the case when it is reported yes or not_sure.
    critical: bool = False


SIGNS: tuple[Sign, ...] = (
    Sign("reduced_appetite", "eating less, or has stopped eating or grazing"),
    Sign("weakness", "dull, weak, lying down more than usual"),
    Sign(
        "swelling",
        "a lump below the ear, under the jaw, or in front of the shoulder "
        "(farmers may call it mbandabvu)",
    ),
    Sign("rapid_breathing", "breathing fast while resting"),
    Sign("cloudy_eye", "the eye looks white, grey or milky", critical=True),
    Sign("froth_nose_mouth", "foam or froth from the nose or mouth", critical=True),
    Sign("red_urine", "urine that is red, brown, or the colour of strong tea"),
    Sign("unable_to_stand", "cannot get up or stay standing", critical=True),
    Sign("ticks", "ticks can be seen on the animal"),
)

SIGN_IDS: tuple[str, ...] = tuple(s.sign_id for s in SIGNS)
SIGN_ID_SET: frozenset[str] = frozenset(SIGN_IDS)
CRITICAL_SIGN_IDS: frozenset[str] = frozenset(s.sign_id for s in SIGNS if s.critical)

SIGN_BY_ID: dict[str, Sign] = {s.sign_id: s for s in SIGNS}


def sign_table() -> str:
    """Render the sign list as the prompt's table."""
    return "\n".join(f"- {s.sign_id}: {s.meaning}" for s in SIGNS)


def critical_list() -> str:
    """Render the critical signs as a readable list for the escalation reason."""
    ordered = [s for s in SIGNS if s.critical]
    return ", ".join(s.sign_id for s in ordered)
