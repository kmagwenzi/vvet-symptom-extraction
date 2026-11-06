"""Request and response models.

The response is exactly the three keys the task specifies. Nothing extra is
added: an unknown field in a contract someone else defined is a change to their
contract, not a feature.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class SignID(str, Enum):
    reduced_appetite = "reduced_appetite"
    weakness = "weakness"
    swelling = "swelling"
    rapid_breathing = "rapid_breathing"
    cloudy_eye = "cloudy_eye"
    froth_nose_mouth = "froth_nose_mouth"
    red_urine = "red_urine"
    unable_to_stand = "unable_to_stand"
    ticks = "ticks"


class SignValue(str, Enum):
    yes = "yes"
    no = "no"
    not_sure = "not_sure"


class Finding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sign_id: SignID
    value: SignValue
    quote: str


class ExtractRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=4000)


class ExtractResponse(BaseModel):
    findings: list[Finding]
    escalate: bool
    reason: str
