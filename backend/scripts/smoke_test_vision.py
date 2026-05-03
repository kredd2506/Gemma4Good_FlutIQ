"""
Smoke test: does Gemma 4 vision work on OpenRouter free tier?

If this passes we can build a Street View flood-indicator agent.
If it fails (or returns garbage), we either need paid OpenRouter or
a Google AI Studio direct-call code path.

Run:
    cd backend && set -a && source .env && set +a && \\
    PYTHONPATH=. .venv/bin/python scripts/smoke_test_vision.py
"""
import asyncio
import base64
import json
import os
import sys

import httpx

API_KEY = os.environ.get("OPENROUTER_API_KEY", "").strip()
BASE = "https://openrouter.ai/api/v1/chat/completions"
PRIMARY = "google/gemma-4-31b-it:free"
FALLBACK = "google/gemma-4-26b-a4b-it:free"

HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
    "HTTP-Referer": "https://flutiq.pages.dev",
    "X-Title": "FlutIQ vision smoke test",
}

# Hotlink-friendly source. Picsum gives us a real photograph (random
# subject) at our requested size — fine for "does vision work at all".
# We test flood-indicator extraction separately with a known building
# image.
TEST_IMAGE_URL = "https://picsum.photos/seed/flutiq-vision-test/640/480"


def section(title: str) -> None:
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


async def fetch_image_as_data_url(url: str) -> str:
    """Download an image and return it as a data: URL (base64-encoded).

    Mirrors the production pattern: we'll fetch Google Street View
    images server-side, then send them inline to Gemma 4. This is
    more reliable than passing a public URL (which the upstream
    fetcher may not be able to reach due to User-Agent rules).
    """
    # Realistic UA — Wikimedia in particular rejects clients without one.
    headers = {"User-Agent": "FlutIQ/1.0 (smoke test)"}
    async with httpx.AsyncClient(timeout=30, headers=headers, follow_redirects=True) as client:
        resp = await client.get(url)
    resp.raise_for_status()
    ct = resp.headers.get("content-type", "image/jpeg").split(";")[0].strip()
    b64 = base64.b64encode(resp.content).decode("ascii")
    return f"data:{ct};base64,{b64}"


async def call(model: str, prompt: str, image_url: str) -> dict:
    payload = {
        "model": model,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": image_url}},
            ],
        }],
        "max_tokens": 1024,
        "temperature": 0.2,
    }
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(BASE, headers=HEADERS, json=payload)
    print(f"  HTTP {resp.status_code}")
    if resp.status_code != 200:
        print(f"  body (first 800 chars): {resp.text[:800]}")
        return {}
    return resp.json()


async def test_describe(model: str, image_url: str) -> bool:
    section(f"TEST 1 — basic image describe ({model})")
    data = await call(
        model,
        "What kind of building is shown in this photo? Answer in one sentence.",
        image_url,
    )
    if not data:
        return False
    msg = data.get("choices", [{}])[0].get("message", {})
    text = msg.get("content", "") or ""
    print(f"  response: {text[:400]!r}")
    print(f"  usage: {data.get('usage', {})}")
    return bool(text and len(text.strip()) > 5)


async def test_flood_indicators(model: str, image_url: str) -> bool:
    section(f"TEST 2 — flood-risk indicator extraction ({model})")
    prompt = """You are a flood risk surveyor analyzing a street-level photo of a residential building.

Identify visible flood risk indicators. For each one you find, note its
location in the image and what it implies about flood vulnerability.

Look specifically for:
- Basement-level windows (vulnerable to surface flooding)
- Ground-floor HVAC units, water heaters, electrical panels
- Below-grade entries or stairwells
- Visible drainage infrastructure (downspouts, storm drains, swales)
- Evidence of prior water damage (staining, repairs)
- Property elevation relative to street grade
- Proximity to obvious water features

Return ONLY a JSON object with this shape:
{
  "indicators": [
    {"feature": "<short name>", "location": "<where in image>", "risk_implication": "<1 sentence>"}
  ],
  "overall_visual_risk": "low" | "moderate" | "high",
  "confidence": "low" | "medium" | "high",
  "summary": "<1 sentence>"
}"""
    data = await call(model, prompt, image_url)
    if not data:
        return False
    msg = data.get("choices", [{}])[0].get("message", {})
    text = msg.get("content", "") or ""
    print(f"  raw response (first 800 chars): {text[:800]}")

    # Try to parse JSON
    clean = text.strip()
    if clean.startswith("```"):
        clean = clean.split("\n", 1)[1] if "\n" in clean else clean[3:]
        if clean.endswith("```"):
            clean = clean.rsplit("```", 1)[0]
        clean = clean.strip()
        if clean.startswith("json"):
            clean = clean[4:].strip()
    try:
        parsed = json.loads(clean)
        print()
        print("  PARSED JSON:")
        print(json.dumps(parsed, indent=4))
        return True
    except json.JSONDecodeError as e:
        print(f"  JSON parse failed: {e}")
        return False


async def main() -> int:
    if not API_KEY:
        print("ERROR: OPENROUTER_API_KEY not set", file=sys.stderr)
        return 2

    print(f"Fetching test image: {TEST_IMAGE_URL}")
    try:
        image = await fetch_image_as_data_url(TEST_IMAGE_URL)
        decoded_bytes = (len(image) - len(image.split(",")[0]) - 1) * 3 // 4
        print(f"  → got {len(image)} chars of data URL ({decoded_bytes} bytes raw)")
    except Exception as e:
        print(f"  failed to fetch test image: {e}", file=sys.stderr)
        return 2

    results = {}
    for model in (PRIMARY, FALLBACK):
        try:
            results[(model, "describe")] = await test_describe(model, image)
        except Exception as e:
            print(f"  EXCEPTION: {type(e).__name__}: {e}")
            results[(model, "describe")] = False

        await asyncio.sleep(2)  # be polite to free tier

        try:
            results[(model, "flood_indicators")] = await test_flood_indicators(model, image)
        except Exception as e:
            print(f"  EXCEPTION: {type(e).__name__}: {e}")
            results[(model, "flood_indicators")] = False

        await asyncio.sleep(2)

    section("SUMMARY")
    for (model, name), ok in results.items():
        mark = "PASS" if ok else "FAIL"
        print(f"  [{mark}] {model:42s} {name}")

    any_describe_passed = any(
        results.get((m, "describe"), False) for m in (PRIMARY, FALLBACK)
    )
    any_flood_passed = any(
        results.get((m, "flood_indicators"), False) for m in (PRIMARY, FALLBACK)
    )

    print()
    if any_describe_passed and any_flood_passed:
        print("VERDICT: Vision works on free tier. Street View agent is buildable.")
        return 0
    elif any_describe_passed:
        print("VERDICT: Vision works for description but JSON-mode flood-indicator")
        print("         extraction is unreliable. Buildable but with retry logic.")
        return 0
    else:
        print("VERDICT: Vision does NOT work on this free-tier route.")
        print("         Need either paid OpenRouter or Google AI Studio direct.")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
