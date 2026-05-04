"""
Satellite-image analysis agent — Gemma 4 vision over a Mapbox
satellite tile, producing structured findings about the property's
catchment, surfaces, and visible drainage features.

This is the bird's-eye companion to the eye-level streetview agent.
Each one runs an independent Gemma 4 vision call against its own
image, returns per-feature bounding boxes (yxyx normalized 0-1000),
and surfaces a 1-sentence summary for the live SSE feed. The risk
analyst then synthesizes across both agents' text findings AND the
raw images themselves.

Returns gracefully (available=False) when MAPBOX_ACCESS_TOKEN isn't
configured — the dossier just doesn't render the Satellite tab.
"""
from app.data.languages import prompt_directive
from app.llm.client import call_gemma4, extract_text, parse_json_response
from app.tools.mapbox import get_satellite_image


SYSTEM_PROMPT = """You are a flood-risk surveyor analyzing an aerial / satellite image of a residential or small-commercial property and its surrounding block. Your job is to extract structured visual signal that text-only data sources cannot provide.

Critical rules:
- Only describe what you can actually see. NEVER fabricate features.
- The property is at the CENTER of the image. Use the full frame to
  reason about catchment context (i.e. what drains TO this property
  from the surrounding block).
- Distinguish "I see X clearly" (high confidence) from "I think this
  might be Y based on coloring" (medium / low confidence).
- For each notable feature, draw a tight bounding box in yxyx
  normalized 0-1000 coordinates (top-left origin), as `box_2d`.

What to look for:
- Impervious surface percentage (concrete + asphalt + roof) vs
  permeable ground (grass, soil, vegetation). This is the single
  biggest predictor of urban flooding. Estimate as % of visible area.
- Building footprint relative to lot — a building covering 90% of
  its lot has near-zero infiltration capacity.
- Roof type: large flat roofs dump massive volumes through downspouts
  during storms; pitched residential roofs are smaller.
- Visible drainage infrastructure: culverts, retention basins, swales,
  ditches, stormwater ponds, French drains.
- Water bodies in or near frame: creeks, ponds, drainage channels,
  retention ponds, lakes, rivers.
- Adjacent land use: paved parking lots and large impervious
  neighbors drain TO this property. A heavily-paved block creates a
  catchment effect concentrating runoff into the local sewer.
- Vegetation buffer: trees, lawns, gardens around the property
  provide infiltration capacity.

Always respond with valid JSON only."""


async def run_satellite_agent(
    lat: float,
    lon: float,
    address: str,
    language: str = "en",
) -> dict:
    sat = await get_satellite_image(lat, lon)

    if not sat:
        return {
            "available": False,
            "summary": (
                "Satellite imagery unavailable — MAPBOX_ACCESS_TOKEN "
                "is not configured on this deployment."
            ),
        }

    user_prompt = f"""Analyze this aerial / satellite image of {address}, taken from
~{int(360 * 40075000 / 2**(sat['zoom']+8) * 600 / 360):,}m altitude
(Mapbox `{sat['style']}`, zoom {sat['zoom']}, ~150m across the frame).

The property is at the CENTER of the image. Identify visible flood-risk
indicators and draw a tight bounding box (yxyx normalized 0-1000, top-left origin)
around each notable feature. Return a JSON object with:

{{
  "indicators": [
    {{
      "feature": "<short name, e.g. 'large asphalt parking lot' / 'flat commercial roof' / 'permeable backyard' / 'drainage retention pond'>",
      "category": "impervious" | "drainage" | "water_body" | "vegetation" | "building" | "other",
      "risk_implication": "<1 sentence on why this affects flood risk for the property>",
      "severity": "low" | "moderate" | "high",
      "box_2d": [y_min, x_min, y_max, x_max]
    }}
  ],
  "impervious_estimate_pct": <int 0-100, your visual estimate of impervious surface coverage in the visible frame>,
  "building_footprint_pct": <int 0-100, what percent of the property's lot the building covers, or null if unclear>,
  "catchment_assessment": "<1-2 sentences on whether the surrounding block drains TO this property based on what you see>",
  "drainage_features_visible": <int, count of explicit drainage features (basins, channels, swales)>,
  "vegetation_buffer": "minimal" | "modest" | "substantial",
  "overall_visual_risk": "low" | "moderate" | "high",
  "confidence": "low" | "medium" | "high",
  "summary": "<1 sentence for the status feed>"
}}

If the image is poor quality, obstructed, or doesn't show a clear
view of the property and its surroundings, set confidence=low and
explain in summary; do not invent indicators.

Return ONLY the JSON object."""

    response = await call_gemma4(
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT + prompt_directive(language)},
            {"role": "user", "content": [
                {"type": "text", "text": user_prompt},
                {"type": "image_url", "image_url": {"url": sat["data_url"]}},
            ]},
        ],
        temperature=0.2,
        max_tokens=2000,
    )

    text = extract_text(response)
    parsed = parse_json_response(text) or {}

    # Validate per-indicator bounding boxes (same rules as streetview).
    cleaned = []
    for ind in parsed.get("indicators") or []:
        if not isinstance(ind, dict):
            continue
        box = ind.get("box_2d")
        if (
            isinstance(box, (list, tuple))
            and len(box) == 4
            and all(isinstance(v, (int, float)) for v in box)
            and all(0 <= v <= 1000 for v in box)
            and box[0] < box[2] and box[1] < box[3]
        ):
            ind["box_2d"] = [float(v) for v in box]
        else:
            ind.pop("box_2d", None)
        cleaned.append(ind)
    parsed["indicators"] = cleaned

    parsed["available"] = True
    parsed["image_data_url"] = sat["data_url"]
    parsed["style"] = sat.get("style")
    parsed["zoom"] = sat.get("zoom")
    parsed.setdefault("summary", "Satellite analysis complete")
    return parsed
