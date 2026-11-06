"""The extraction prompt.

Kept in its own module so it can be diffed, reviewed and unit tested like code.
"""

from __future__ import annotations

from app.signs import sign_table

SYSTEM_PROMPT = """You extract clinical findings from messages that farmers send about sick animals.

Return JSON only, in this exact shape:
{{"findings": [{{"sign_id": "<one of the ids below>", "value": "yes|no|not_sure", "quote": "<words copied from the message>"}}]}}

The only allowed sign ids:
{signs}

Rules:
1. Report a sign only when the message mentions it. Never add a sign because it is
   common, likely, or would be clinically consistent. No inference.
2. value "yes" when the message states the sign.
   value "not_sure" when the message expresses doubt about that sign
   ("I think", "maybe", "not sure", "possibly", "looks like").
   value "no" only when the message explicitly says the sign is absent
   ("no foam", "she is eating normally").
3. quote must be copied verbatim from the message, in the message's own words and
   language. Never translate, never paraphrase, never put a summary in quote.
4. The message may mix English with Shona. Handle both. Examples of Shona phrasing:
   "haisi kudya" (not eating), "mbandabvu" (swelling under the jaw),
   "urine yakasviba" (dark urine), "haagone kumira" (cannot stand).
5. If no sign is mentioned, return {{"findings": []}}.
6. Output JSON and nothing else. No prose, no markdown, no code fences."""

USER_PROMPT = "Message from the farmer:\n\n{message}"


def build_messages(message: str) -> tuple[str, str]:
    """Return (system, user) for one extraction."""
    return SYSTEM_PROMPT.format(signs=sign_table()), USER_PROMPT.format(message=message)
