"""HTTP surface: one endpoint, plus a health check."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException

from app import __version__
from app.escalate import decide_escalation
from app.extract import Extractor, enforce_contract, get_extractor
from app.llm import LLMError
from app.schema import ExtractRequest, ExtractResponse
from app.signs import SIGN_IDS, critical_list
from app.validate import ExtractionError

@asynccontextmanager
async def lifespan(_: FastAPI):
    """Fail fast on a bad EXTRACTOR value instead of 500-ing on every request."""
    get_extractor()
    yield


app = FastAPI(
    title="V-Vet symptom extraction",
    version=__version__,
    description="Turns a farmer's WhatsApp message into structured clinical findings.",
    lifespan=lifespan,
)


@app.get("/health")
def health(extractor: Extractor = Depends(get_extractor)) -> dict[str, object]:
    return {
        "status": "ok",
        "version": __version__,
        "extractor": extractor.name,
        "signs": len(SIGN_IDS),
        "critical": critical_list(),
    }


@app.post("/extract", response_model=ExtractResponse)
def extract(
    request: ExtractRequest, extractor: Extractor = Depends(get_extractor)
) -> ExtractResponse:
    try:
        result = enforce_contract(extractor.extract(request.message), request.message)
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=f"model unavailable: {exc}") from exc
    except ExtractionError as exc:
        raise HTTPException(
            status_code=502, detail=f"model answer rejected: {exc}"
        ) from exc

    escalate, reason = decide_escalation(result.findings)

    notes = [*result.dropped, *result.repaired]
    if notes:
        reason = f"{reason} Validation notes: {'; '.join(notes)}."

    return ExtractResponse(findings=result.findings, escalate=escalate, reason=reason)
