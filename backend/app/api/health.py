from fastapi import APIRouter

from app.config import OPENROUTER_API_KEY

router = APIRouter()


@router.get("/api/health")
async def health() -> dict:
    return {
        "status": "ok",
        "openrouter_key_configured": bool(OPENROUTER_API_KEY),
    }
