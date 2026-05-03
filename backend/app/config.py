"""Environment configuration."""
import os

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_BASE = "https://openrouter.ai/api/v1"

MODEL_PRIMARY = "google/gemma-4-31b-it:free"
MODEL_FALLBACK = "google/gemma-4-26b-a4b-it:free"

APP_NAME = "FloodIQ"
APP_URL = "https://floodiq.pages.dev"
USER_AGENT = "FloodIQ/1.0 (floodiq.pages.dev)"
