from fastapi import APIRouter

from app.config import INFERENCE_BACKEND, MODEL_PRIMARY, OPENROUTER_API_KEY

router = APIRouter()


@router.get("/api/health")
async def health() -> dict:
    return {
        "status": "ok",
        "inference_backend": INFERENCE_BACKEND,
        "model": MODEL_PRIMARY,
        "openrouter_key_configured": bool(OPENROUTER_API_KEY),
    }
