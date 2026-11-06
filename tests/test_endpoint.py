"""The HTTP contract: exactly three keys, and honest failures."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.extract import RuleExtractor, get_extractor
from app.llm import LLMError
from app.main import app
from app.validate import ExtractionError
from tests.conftest import client_for, finding


def test_response_has_exactly_the_three_contract_keys():
    client, _ = client_for([finding("ticks", "yes", "lots of ticks")])
    response = client.post("/extract", json={"message": "lots of ticks"})
    assert response.status_code == 200
    assert set(response.json()) == {"findings", "escalate", "reason"}


def test_findings_are_serialised_as_the_task_specifies():
    client, _ = client_for([finding("ticks", "yes", "lots of ticks")])
    body = client.post("/extract", json={"message": "lots of ticks"}).json()
    assert body["findings"] == [
        {"sign_id": "ticks", "value": "yes", "quote": "lots of ticks"}
    ]


def test_message_is_passed_through_untouched():
    client, fake = client_for([])
    message = "Mombe yangu haisi kudya, and her urine is dark like tea."
    client.post("/extract", json={"message": message})
    assert fake.seen == [message]


def test_empty_message_is_rejected():
    client, _ = client_for([])
    assert client.post("/extract", json={"message": ""}).status_code == 422


def test_unknown_request_field_is_rejected():
    client, _ = client_for([])
    response = client.post("/extract", json={"message": "hello", "lang": "sn"})
    assert response.status_code == 422


def test_model_outage_is_a_502_not_a_500():
    client, _ = client_for(error=LLMError("provider timed out"))
    response = client.post("/extract", json={"message": "foam from the nose"})
    assert response.status_code == 502
    assert "provider timed out" in response.json()["detail"]


def test_unusable_model_answer_is_a_502():
    client, _ = client_for(error=ExtractionError("no JSON object found"))
    response = client.post("/extract", json={"message": "foam from the nose"})
    assert response.status_code == 502


def test_validation_notes_reach_the_reason():
    client, _ = client_for(
        [
            # ungrounded and non-critical: dropped, and the caller is told why
            finding("weakness", "yes", "she looks exhausted"),
            finding("ticks", "yes", "ticks"),
        ]
    )
    body = client.post(
        "/extract", json={"message": "The calf is fine, just lots of ticks."}
    ).json()
    assert [f["sign_id"] for f in body["findings"]] == ["ticks"]
    assert "Validation notes" in body["reason"]


def test_health_reports_the_active_extractor():
    app.dependency_overrides[get_extractor] = lambda: RuleExtractor()
    body = TestClient(app).get("/health").json()
    assert body["extractor"] == "rule"
    assert body["signs"] == 9
