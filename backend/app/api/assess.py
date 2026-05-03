"""POST /api/assess — SSE stream of agent updates ending with a dossier."""
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.agents.orchestrator import run_assessment

router = APIRouter()


class AssessRequest(BaseModel):
    address: str = Field(..., min_length=3, max_length=300)


@router.post("/api/assess")
async def assess(req: AssessRequest):
    return StreamingResponse(
        run_assessment(req.address),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
