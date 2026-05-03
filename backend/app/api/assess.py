"""POST /api/assess — SSE stream of agent updates ending with a dossier."""
from typing import Optional

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.agents.orchestrator import run_assessment

router = APIRouter()


class AssessRequest(BaseModel):
    address: str = Field(..., min_length=3, max_length=300)
    language: Optional[str] = Field(
        "en",
        description=(
            "ISO 639-1 code for the language of user-facing dossier copy. "
            "Supported: en, es, zh, vi, ht, ar, tl. Unknown codes silently "
            "fall back to en."
        ),
    )


@router.post("/api/assess")
async def assess(req: AssessRequest):
    return StreamingResponse(
        run_assessment(req.address, language=req.language or "en"),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
