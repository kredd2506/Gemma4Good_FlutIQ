"""
Street View flood-indicator agent — the multimodal Gemma 4 showcase.

Fetches a Google Street View image at the property, then asks Gemma 4
(vision) to identify visible flood-risk features: basement-level
windows, ground-floor HVAC, below-grade entries, drainage
infrastructure, evidence of prior water damage, elevation relative
to street grade.

This is the only agent that exercises Gemma 4's multimodal capability.
Verified to work on the :free tier with BYOK in scripts/smoke_test_vision.py.

Returns the verdict alongside the image (data URL) so the dossier UI
can show a thumbnail next to the findings.
"""
from app.data.languages import prompt_directive
from app.llm.client import call_gemma4, extract_text, parse_json_response
from app.tools.streetview import fetch_streetview_for


SYSTEM_PROMPT = """You are a flood-risk surveyor analyzing a street-level photograph of a residential or small-commercial property. Your job is to identify visible features in the image that affect flood vulnerability AND localize each one with a 2D bounding box.

Critical rules:
- Only describe features you can actually see. NEVER fabricate a feature to fill the JSON.
- If the image is partially obstructed, low quality, or doesn't show the property clearly, say so via "confidence": "low" and a short summary explaining what's missing. Return indicators=[] in that case rather than guessing.
- Distinguish "I see X and it implies Y" from "I'd want to verify Y by looking inside."
- For every indicator you do return, include a tight bounding box around just that feature.

Bounding box format (this is the Gemini 2 vision convention — follow it exactly):
- Field name: "box_2d"
- Order: [y_min, x_min, y_max, x_max]
- Coordinates are NORMALIZED to a 0-1000 grid where (0, 0) is the top-left of the image and (1000, 1000) is the bottom-right.
- y is the vertical axis (top to bottom). x is the horizontal axis (left to right).
- Example: a feature in the top-left quarter of the image might be [120, 80, 480, 420].

What to look for, in plain language:
- Basement-level windows (small, below sidewalk level, sometimes with metal grating) — vulnerable to surface water entering directly
- Ground-floor HVAC units, water heaters, electrical meters mounted at low elevation — expensive to replace if submerged
- Below-grade entries, basement stairwells, driveways sloping toward the building
- Visible downspouts that discharge into hard surfaces or storm drains rather than landscaping
- Storm drains, swales, retaining walls, French drains, sandbags
- Watermarks, staining, repair patches, or rust — evidence of past water exposure
- The property's elevation relative to the street and neighboring buildings (sunken vs raised)
- Proximity to obvious water features (canals, low-lying parks, creeks)

Always respond with valid JSON only."""


async def run_streetview_agent(
    lat: float,
    lon: float,
    address: str,
    language: str = "en",
) -> dict:
    sv = await fetch_streetview_for(lat, lon)

    if not sv.get("available"):
        return {
            "available": False,
            "summary": (
                "No street-level imagery available for this address — "
                "Google Street View has no panorama within 500m."
            ),
            "raw": sv,
        }

    user_prompt = f"""Examine this street-level photo of the property at {address}.

The photo was captured by Google Street View in {sv.get('capture_date') or 'an unknown date'} from
approximately ({sv.get('pano_lat'):.5f}, {sv.get('pano_lon'):.5f})
{f"— {sv.get('radius_m')}m from the geocoded address" if sv.get('radius_m') else "— at the geocoded address"}.

Identify visible flood-risk indicators AND draw a tight bounding box around each one. Return a JSON object with:
{{
  "indicators": [
    {{
      "feature": "<short name, e.g. 'basement-level windows'>",
      "location_in_image": "<e.g. 'lower-left of the building facade'>",
      "risk_implication": "<1 sentence on what this means for flood risk>",
      "severity": "low" | "moderate" | "high",
      "box_2d": [y_min, x_min, y_max, x_max]   // normalized 0-1000, see system prompt
    }}
  ],
  "property_visible": true | false,
  "image_quality": "good" | "partial" | "poor",
  "elevation_vs_street": "below_grade" | "at_grade" | "elevated" | "unclear",
  "overall_visual_risk": "low" | "moderate" | "high",
  "confidence": "low" | "medium" | "high",
  "summary": "<1 sentence for the status feed>"
}}

If you can't see the property clearly (image obstructed, wrong angle, distant
street), set property_visible=false and confidence=low; don't invent indicators.

Return ONLY the JSON object."""

    response = await call_gemma4(
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT + prompt_directive(language)},
            {"role": "user", "content": [
                {"type": "text", "text": user_prompt},
                {"type": "image_url", "image_url": {"url": sv["image_data_url"]}},
            ]},
        ],
        temperature=0.2,
        max_tokens=1500,
    )

    text = extract_text(response)
    parsed = parse_json_response(text) or {}

    # Validate per-indicator bounding boxes. Drop any box_2d that isn't
    # a valid 4-tuple of numbers in [0, 1000]. The frontend trusts that
    # every box on a passed-through indicator is renderable as-is.
    cleaned_indicators = []
    for ind in parsed.get("indicators") or []:
        if not isinstance(ind, dict):
            continue
        box = ind.get("box_2d")
        if (
            isinstance(box, (list, tuple))
            and len(box) == 4
            and all(isinstance(v, (int, float)) for v in box)
            and all(0 <= v <= 1000 for v in box)
            and box[0] < box[2] and box[1] < box[3]  # ymin<ymax, xmin<xmax
        ):
            ind["box_2d"] = [float(v) for v in box]
        else:
            ind.pop("box_2d", None)  # keep indicator, drop bad box
        cleaned_indicators.append(ind)
    if cleaned_indicators:
        parsed["indicators"] = cleaned_indicators

    # Always attach the image data URL + provenance so the UI can render
    # the thumbnail and credit Google for the imagery.
    parsed["available"] = True
    parsed["image_data_url"] = sv["image_data_url"]
    parsed["pano_id"] = sv.get("pano_id")
    parsed["capture_date"] = sv.get("capture_date")
    parsed["copyright"] = sv.get("copyright")
    parsed["pano_distance_m"] = sv.get("radius_m")

    if "summary" not in parsed:
        parsed["summary"] = "Street-level survey complete"
    if not parsed.get("indicators"):
        parsed.setdefault("indicators", [])
    parsed.setdefault("raw_text", text if not parse_json_response(text) else None)
    if parsed["raw_text"] is None:
        parsed.pop("raw_text", None)

    return parsed
