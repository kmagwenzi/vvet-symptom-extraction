"""Shared test fixtures.

Every test in this suite runs with no network and no API key. The model is
replaced at the extractor boundary, which is the seam the application actually
depends on.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.extract import ExtractionResult, get_extractor
from app.main import app
from app.schema import Finding, SignID, SignValue


def finding(sign_id: str, value: str, quote: str) -> Finding:
    return Finding(sign_id=SignID(sign_id), value=SignValue(value), quote=quote)


class FakeExtractor:
    """Stands in for the LLM. Returns scripted findings or raises."""

    name = "fake"

    def __init__(self, findings=None, error: Exception | None = None) -> None:
        self.findings = findings or []
        self.error = error
        self.seen: list[str] = []

    def extract(self, message: str) -> ExtractionResult:
        self.seen.append(message)
        if self.error is not None:
            raise self.error
        return ExtractionResult(findings=list(self.findings), mode=self.name)


def client_for(findings=None, error=None) -> tuple[TestClient, FakeExtractor]:
    fake = FakeExtractor(findings=findings, error=error)
    app.dependency_overrides[get_extractor] = lambda: fake
    return TestClient(app), fake


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()
