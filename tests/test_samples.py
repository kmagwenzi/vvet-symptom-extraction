"""The five sample messages, end to end through the pipeline.

The model is scripted here: each case supplies the answer a good model would
give. That keeps the test offline while still exercising validation, escalation
and serialisation on the real messages.
"""

from __future__ import annotations

import pytest

from tests.conftest import client_for, finding

CASES = [
    {
        "name": "not eating and breathing fast",
        "message": "My cow has not been eating since yesterday and she is breathing very fast.",
        "model": [
            finding("reduced_appetite", "yes", "has not been eating since yesterday"),
            finding("rapid_breathing", "yes", "breathing very fast"),
        ],
        "expect_signs": ["reduced_appetite", "rapid_breathing"],
        "escalate": False,
    },
    {
        "name": "foam and cannot stand",
        "message": "There's foam coming from her nose and she can't get up.",
        "model": [
            finding("froth_nose_mouth", "yes", "foam coming from her nose"),
            finding("unable_to_stand", "yes", "she can't get up"),
        ],
        "expect_signs": ["froth_nose_mouth", "unable_to_stand"],
        "escalate": True,
    },
    {
        "name": "uncertain eye, definite swelling",
        "message": "I think the eyes look a bit cloudy but I'm not sure. She has mbandabvu under the ear.",
        "model": [
            finding("cloudy_eye", "not_sure", "I think the eyes look a bit cloudy but I'm not sure"),
            finding("swelling", "yes", "mbandabvu under the ear"),
        ],
        "expect_signs": ["swelling", "cloudy_eye"],  # canonical sign order
        "escalate": True,
    },
    {
        "name": "healthy calf with ticks",
        "message": "The calf is fine, just lots of ticks on the ears.",
        "model": [finding("ticks", "yes", "lots of ticks on the ears")],
        "expect_signs": ["ticks"],
        "escalate": False,
    },
    {
        "name": "Shona and English mixed",
        "message": "Mombe yangu haisi kudya, and her urine is dark like tea.",
        "model": [
            finding("reduced_appetite", "yes", "haisi kudya"),
            finding("red_urine", "yes", "her urine is dark like tea"),
        ],
        "expect_signs": ["reduced_appetite", "red_urine"],
        "escalate": False,
    },
]


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_sample_message_end_to_end(case):
    client, _ = client_for(case["model"])
    body = client.post("/extract", json={"message": case["message"]}).json()
    assert [f["sign_id"] for f in body["findings"]] == case["expect_signs"]
    assert body["escalate"] is case["escalate"]
    for item in body["findings"]:
        assert item["quote"] in case["message"]


def test_an_invented_non_critical_sign_is_dropped():
    client, _ = client_for(
        [
            finding("ticks", "yes", "lots of ticks on the ears"),
            finding("weakness", "yes", "she looks exhausted"),
        ]
    )
    body = client.post(
        "/extract", json={"message": "The calf is fine, just lots of ticks on the ears."}
    ).json()
    assert [f["sign_id"] for f in body["findings"]] == ["ticks"]
    assert body["escalate"] is False


def test_an_invented_critical_sign_is_downgraded_not_deleted():
    """The deliberate asymmetry.

    An ungrounded quote on a critical sign is kept as not_sure rather than
    deleted, so a model that paraphrases a real emergency cannot silence it. The
    cost is a false alarm when the model invents one outright; that is the
    cheaper mistake in triage, and the reason is returned to the caller.
    """
    client, _ = client_for(
        [
            finding("ticks", "yes", "lots of ticks on the ears"),
            finding("froth_nose_mouth", "yes", "white foam around the mouth"),
        ]
    )
    body = client.post(
        "/extract", json={"message": "The calf is fine, just lots of ticks on the ears."}
    ).json()
    assert [f["sign_id"] for f in body["findings"]] == ["froth_nose_mouth", "ticks"]
    assert body["findings"][0]["value"] == "not_sure"
    assert body["escalate"] is True
    assert "not grounded" in body["reason"]
