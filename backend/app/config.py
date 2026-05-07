"""Environment configuration."""
import os

# .strip() defends against trailing whitespace / newlines from web-UI
# paste flows (HF Spaces secrets UI adds a trailing \n which makes httpx
# reject the Authorization header as an illegal value).
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "").strip()
GOOGLE_MAPS_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY", "").strip()
MAPBOX_ACCESS_TOKEN = os.environ.get("MAPBOX_ACCESS_TOKEN", "").strip()

# INFERENCE_BACKEND switches the LLM endpoint without touching agent code.
#   "openrouter" (default) → cloud Gemma 4 via OpenRouter (production / HF Space)
#   "ollama"               → local Gemma 4 via Ollama at localhost:11434
# Both targets speak OpenAI-compatible /v1/chat/completions, so the client
# code path is shared. See FLUTIQ_OLLAMA_LOCAL.md for why this exists.
INFERENCE_BACKEND = os.environ.get("INFERENCE_BACKEND", "openrouter").strip().lower()

if INFERENCE_BACKEND == "ollama":
    LLM_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1").strip()
    # Ollama doesn't require a real key but the OpenAI-compatible layer
    # still expects an Authorization header to parse, so send a placeholder.
    LLM_API_KEY = "ollama"
    MODEL_PRIMARY = os.environ.get("OLLAMA_MODEL", "gemma4:e4b").strip()
    # No separate fallback locally — same model, same hardware, same speed.
    MODEL_FALLBACK = MODEL_PRIMARY
else:
    LLM_BASE_URL = "https://openrouter.ai/api/v1"
    LLM_API_KEY = OPENROUTER_API_KEY
    MODEL_PRIMARY = "google/gemma-4-31b-it:free"
    MODEL_FALLBACK = "google/gemma-4-26b-a4b-it:free"

# Legacy alias so any external script still importing OPENROUTER_BASE keeps
# working when the backend is in cloud mode. New code should prefer
# LLM_BASE_URL.
OPENROUTER_BASE = LLM_BASE_URL if INFERENCE_BACKEND == "openrouter" else "https://openrouter.ai/api/v1"

APP_NAME = "FlutIQ"
APP_URL = "https://flutiq.pages.dev"
USER_AGENT = "FlutIQ/1.0 (flutiq.pages.dev)"
