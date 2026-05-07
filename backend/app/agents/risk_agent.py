"""Risk-analyst agent — THE Gemma 4 reasoning showcase.

As of v0.9 this agent is **multimodal**: it receives the Street View
photograph of the property as an `image_url` content part alongside
the text data from every other agent, with reasoning mode enabled.
That means a single Gemma 4 inference pass composes:

  - Image understanding (the property photo)
  - Reasoning mode (chain-of-thought trace)
  - Interleaved multimodal input (image + text mixed in one prompt)
  - Structured JSON output (the dossier risk schema)
  - Long context (~6-10K text tokens + image tokens)

The chain-of-thought trace is preserved on the dossier — the model
is explicitly asked to weave together what it SEES in the photo with
what the data SAYS, so the trace reads like a single mind reasoning
across both modalities, not like one agent summarizing another's
notes.

Per Gemma 4 best practice, the image is placed BEFORE the text in
the user message content array.
"""
import json
from typing import Optional

from app.data.languages import prompt_directive
from app.llm.client import (
    call_gemma4,
    extract_reasoning,
    extract_text,
    parse_json_response,
)
from app.llm.prompts import RISK_AGENT_SYSTEM_PROMPT


async def run_risk_agent(
    all_data: dict,
    lat: float,
    lon: float,
    address: str,
    language: str = "en",
    streetview_image_data_url: Optional[str] = None,
    satellite_image_data_url: Optional[str] = None,
) -> dict:
    image_data_urls = [
        ("satellite", satellite_image_data_url),
        ("streetview", streetview_image_data_url),
    ]
    image_data_urls = [(k, u) for k, u in image_data_urls if u]
    image_count = len(image_data_urls)
    image_kinds = [k for k, _ in image_data_urls]
    has_image = image_count > 0

    image_section = ""
    if has_image:
        # Describe ONLY the images we actually have, in the order we
        # send them. Order matches the content_parts list below so
        # "first image" / "second image" references are accurate.
        labels = []
        descriptions = []
        if "satellite" in image_kinds:
            labels.append(f"image {len(labels)+1} = SATELLITE VIEW (bird's-eye)")
            descriptions.append(
                "- SATELLITE: a dedicated satellite agent has already analyzed "
                "this image and produced structured findings (impervious_estimate_pct, "
                "indicators with bounding boxes, catchment_assessment, etc.) — see "
                "the 'Satellite Visual Analysis' section below. Look at the image "
                "yourself to verify or extend those findings: the property is at "
                "the CENTER of the frame; everything around it is the catchment."
            )
        if "streetview" in image_kinds:
            labels.append(f"image {len(labels)+1} = STREET VIEW (eye-level)")
            descriptions.append(
                "- STREET VIEW: a dedicated streetview agent has already analyzed "
                "this image and produced indicators with bounding boxes — see "
                "'Street View Visual Analysis' below. Look at the image yourself "
                "to verify lot elevation vs street grade, basement-level windows, "
                "below-grade entries, downspout connections, ground-floor HVAC, "
                "and evidence of prior water damage."
            )
        labels_block = "\n".join(f"  · {l}" for l in labels)
        desc_block = "\n".join(descriptions)
        image_section = f"""
## Property images ({image_count} attached, in order above this text)
{labels_block}

EXAMINE EACH IMAGE YOURSELF before reading the data sections.
{desc_block}

Cross-reference what you see across the images. When evidence from
one view corroborates or contradicts another view, OR when visual
evidence corroborates or contradicts the data, say so explicitly in
your reasoning. Reference images by name ("from the satellite I can
see...", "in the street view...").
"""

    text_prompt = f"""You are analyzing flood risk for: {address} ({lat}, {lon})
{image_section}
Here is all the data collected by our investigation team:

## FEMA Expert Findings
{json.dumps(all_data.get('fema', {}), indent=2, default=str)}

## Local Infrastructure Findings (311 data, sewer type)
{json.dumps(all_data.get('local', {}), indent=2, default=str)}

## Street View Visual Analysis (from the streetview agent)
{json.dumps({k: v for k, v in (all_data.get('streetview') or {}).items() if k != 'image_data_url'}, indent=2, default=str)}

## Satellite Visual Analysis (from the satellite agent)
{json.dumps({k: v for k, v in (all_data.get('satellite') or {}).items() if k != 'image_data_url'}, indent=2, default=str)}

## Regional Multi-Hazard Profile (FEMA NRI, county-level — from the regional_risk agent)
This is the COUNTY-level National Risk Index profile — wider than the
property-specific signals above, narrower than national. Use it to widen
the risk story beyond flooding (wildfire, hurricane, tornado, earthquake,
etc. as applicable to this geography). Don't double-count: NRI's Inland
Flooding score is county-level; the FEMA flood zone above is the
authoritative property-level designation.
{json.dumps({k: v for k, v in (all_data.get('regional') or {}).items() if k != 'nri'}, indent=2, default=str)}

## Weather & Hydrology Findings
{json.dumps(all_data.get('weather', {}), indent=2, default=str)}

## Recent Local Flood News
{json.dumps(all_data.get('news', {}), indent=2, default=str)}

## Historical Storm Archive
{json.dumps(all_data.get('archive', {}), indent=2, default=str)}

---

TASK: Synthesize ALL of this data — including your own visual
inspection of the property photo — into a flood risk assessment.

IMPORTANT CONTEXT:
- A "100-year flood" means 1% annual exceedance probability (AEP), NOT once per century
- Formula: P(at least one event in n years) = 1 - (1 - AEP)^n
- Over a 30-year mortgage: 1% AEP = 26% cumulative probability
- FEMA flood maps ONLY measure riverine/coastal flooding
- In cities with combined sewer systems, most flooding is basement sewer backup — FEMA does NOT map this
- If there are many 311 flood reports but FEMA says "minimal risk", the FEMA designation is misleading
- Chicago's sewer system overwhelms after ~0.67 inches of rain per hour

Return a JSON object with:
{{
  "risk_score": <0-100 integer>,
  "risk_level": "low" | "medium" | "high",
  "aep_estimate": <estimated annual exceedance probability as decimal, e.g. 0.04>,
  "mortgage_30yr_probability": <cumulative probability over 30 years, e.g. 0.68>,
  "fema_gap_explanation": "<2-3 sentences explaining if/why FEMA designation is misleading>",
  "visual_corroboration": {"<2-3 sentences on what the photo confirms, contradicts, or adds beyond the data; '' if no image was provided>" if has_image else "''"},
  "key_risk_factors": ["<ranked list of top risk factors>"],
  "mitigating_factors": ["<factors that reduce risk>"],
  "summary": "<1 sentence for the status feed>"
}}

Think step by step. Integrate visual and data evidence. Reference the
photo directly in your reasoning ("I can see ...", "The image shows ...")
when relevant. Return ONLY the JSON object at the end."""

    # Build the user message content. Per Gemma 4 best practice,
    # image content parts go BEFORE the text part. Order matches the
    # 'image N' labels in the prompt.
    user_content: list = []
    for _kind, url in image_data_urls:
        user_content.append({
            "type": "image_url",
            "image_url": {"url": url},
        })
    user_content.append({"type": "text", "text": text_prompt})

    # Some providers prefer a plain string for text-only requests; only
    # send the structured content list when we actually have an image.
    user_message_content = user_content if has_image else text_prompt

    response = await call_gemma4(
        messages=[
            {"role": "system", "content": RISK_AGENT_SYSTEM_PROMPT + prompt_directive(language)},
            {"role": "user", "content": user_message_content},
        ],
        reasoning=True,
        temperature=0.2,
        max_tokens=8192,
    )

    text = extract_text(response)
    reasoning = extract_reasoning(response)

    parsed = parse_json_response(text)
    if parsed:
        parsed["reasoning_trace"] = reasoning
        parsed["used_streetview_image"] = "streetview" in image_kinds
        parsed["images_used"] = image_kinds
        return parsed

    return {
        "risk_score": 50,
        "risk_level": "medium",
        "summary": "Risk analysis returned non-JSON output; using fallback",
        "raw_response": text,
        "reasoning_trace": reasoning,
        "used_streetview_image": "streetview" in image_kinds,
        "images_used": image_kinds,
    }
