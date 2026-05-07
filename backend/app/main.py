from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.assess import router as assess_router
from app.api.health import router as health_router

app = FastAPI(title="FlutIQ", version="0.13.0")

# CORS still permissive for split-deployment scenarios. With the
# bundled deploy (frontend served from FastAPI) it's a no-op because
# the browser is already same-origin.
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

# Serve the bundled frontend from /. Mounted last so the API routes
# above always win.
_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
if _STATIC_DIR.is_dir():
    @app.get("/")
    async def root() -> FileResponse:
        return FileResponse(_STATIC_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")
