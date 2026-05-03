"""Environment configuration."""
import os

# .strip() defends against trailing whitespace / newlines from web-UI
# paste flows (HF Spaces secrets UI adds a trailing \n which makes httpx
# reject the Authorization header as an illegal value).
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "").strip()
GOOGLE_MAPS_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY", "").strip()
MAPBOX_ACCESS_TOKEN = os.environ.get("MAPBOX_ACCESS_TOKEN", "").strip()
OPENROUTER_BASE = "https://openrouter.ai/api/v1"

MODEL_PRIMARY = "google/gemma-4-31b-it:free"
MODEL_FALLBACK = "google/gemma-4-26b-a4b-it:free"

APP_NAME = "FlutIQ"
APP_URL = "https://flutiq.pages.dev"
USER_AGENT = "FlutIQ/1.0 (flutiq.pages.dev)"
