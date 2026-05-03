from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.assess import router as assess_router
from app.api.health import router as health_router

app = FastAPI(title="FloodIQ API", version="0.1.0")

_CORS_ORIGIN_REGEX = (
    r"https?://("
    r"localhost(:\d+)?|"
    r"127\.0\.0\.1(:\d+)?|"
    r".*\.pages\.dev|"
    r".*\.hf\.space"
    r")"
)

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=_CORS_ORIGIN_REGEX,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(assess_router)
