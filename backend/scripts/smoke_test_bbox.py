"""
Smoke test: does Gemma 4 return usable bounding boxes for the
flood-risk indicators it identifies on a Street View image?

We don't assume any specific format. We ask explicitly for boxes,
dump the raw text response, and check what shape comes back:
  - Are the coords [y1,x1,y2,x2] (Gemini convention) or [x1,y1,x2,y2]?
  - Are they 0-1000 normalized, 0-1 normalized, or pixel coordinates?
  - Are they in a JSON field per indicator, or in a separate "boxes"
    array, or as natural-language descriptions?

Run:
    cd backend && set -a && source .env && set +a && \\
    PYTHONPATH=. .venv/bin/python scripts/smoke_test_bbox.py
"""
import asyncio
import json
import sys

import httpx

from app.config import OPENROUTER_API_KEY
from app.tools.streetview import fetch_streetview_for

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "google/gemma-4-31b-it:free"

# Chicago Drexel — confirmed via earlier smoke tests to have Street
# View coverage with the building visible after our bearing-aim fix.
TEST_LAT, TEST_LON = 41.8127384, -87.6045491
TEST_ADDRESS = "4521 S Drexel Blvd, Chicago IL"


def section(title: str) -> None:
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)


# Three different prompt phrasings to see which produces the most
# parseable output. Hackathon judges will recognize the Gemini box
# format — let's see if Gemma does the same thing.
PROMPTS = [
    {
        "name": "explicit Gemini-format request",
        "prompt": """Examine this street-level photo of a residential property.

Detect visible flood-risk indicators (basement-level windows, ground-floor HVAC units, water heaters or electrical meters at low elevation, downspouts, drainage grates, below-grade entries, watermarks, sandbags, low-elevation property relative to street).

For each one, return a 2D bounding box using coordinates normalized to 0-1000 in [y_min, x_min, y_max, x_max] order (top-left origin, like Gemini 2 vision).

Return ONLY a JSON array, one object per detection:
[
  {"label": "<short feature name>", "box_2d": [y_min, x_min, y_max, x_max], "severity": "low" | "moderate" | "high"}
]

If you can't see the property clearly, return an empty array []. Do NOT fabricate detections."""
    },
    {
        "name": "natural ask for coordinates",
        "prompt": """Identify the flood-risk indicators visible in this street-level photo of a residential property. For each indicator, give me the bounding box around it.

Return JSON like:
{
  "image_dims": {"width": <px>, "height": <px>} or null if you don't know,
  "detections": [
    {
      "label": "<short feature name>",
      "bbox": <whatever format you naturally return — describe the format in 'bbox_format'>,
      "bbox_format": "<one of 'xyxy_pixels', 'xyxy_normalized_0_1', 'yxyx_normalized_0_1000', or whatever you used>",
      "severity": "low" | "moderate" | "high"
    }
  ]
}

If you can't see the property clearly, return detections=[]. Do NOT fabricate."""
    },
]


async def call_with_image(prompt: str, image_data_url: str) -> dict:
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://flutiq.pages.dev",
        "X-Title": "FlutIQ bbox smoke test",
    }
    payload = {
        "model": MODEL,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": image_data_url}},
            ],
        }],
        "max_tokens": 2000,
        "temperature": 0.1,
    }
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(OPENROUTER_URL, headers=headers, json=payload)
    print(f"  HTTP {resp.status_code}")
    if resp.status_code != 200:
        print(f"  body: {resp.text[:600]}")
        return {}
    return resp.json()


async def main() -> int:
    if not OPENROUTER_API_KEY:
        print("ERROR: OPENROUTER_API_KEY not set", file=sys.stderr)
        return 2

    print(f"Fetching Street View for {TEST_ADDRESS}...")
    sv = await fetch_streetview_for(TEST_LAT, TEST_LON)
    if not sv.get("available"):
        print(f"  Street View unavailable: {sv.get('reason')}", file=sys.stderr)
        return 2
    print(f"  pano_id={sv['pano_id']} captured={sv['capture_date']} bytes={sv['image_bytes']}")
    image_data_url = sv["image_data_url"]

    for variant in PROMPTS:
        section(f"VARIANT: {variant['name']}")
        data = await call_with_image(variant["prompt"], image_data_url)
        if not data:
            print("  no response")
            continue
        msg = data.get("choices", [{}])[0].get("message", {})
        text = msg.get("content", "") or ""
        usage = data.get("usage", {})
        print(f"  tokens: prompt={usage.get('prompt_tokens')} "
              f"completion={usage.get('completion_tokens')} "
              f"cost=${usage.get('cost', 0)}")
        print()
        print("  RAW RESPONSE:")
        print("  " + "─" * 70)
        for line in text.splitlines():
            print(f"  {line}")
        print("  " + "─" * 70)

        # Try to extract JSON
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
            print(f"\n  PARSED (type={type(parsed).__name__}):")
            print(f"    {json.dumps(parsed, indent=4)[:1500]}")
        except json.JSONDecodeError as e:
            print(f"\n  JSON parse failed: {e}")

        await asyncio.sleep(2)

    section("VERDICT")
    print("Look at the raw responses above.")
    print("Key questions:")
    print("  1. Did the model return numeric box coordinates at all?")
    print("  2. What format? (yxyx normalized 0-1000? xyxy pixels? something else?)")
    print("  3. Did it correctly localize features that are actually in the image?")
    print("  4. Or did it just return text descriptions of locations?")
    print()
    print("If (1) and (2) and (3) are yes → build the SVG overlay.")
    print("If only (4) → fall back to text-only labels (which we already have).")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
