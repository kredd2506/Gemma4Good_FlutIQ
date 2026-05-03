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
) -> dict:
    has_image = bool(streetview_image_data_url)

    image_section = ""
    if has_image:
        image_section = """
## Property photograph (Street View)
A street-level photo of the property is included with this prompt
(it appears immediately above this text). EXAMINE IT YOURSELF before
reading the data sections. Look for:
- Lot elevation relative to street grade (above, level, or below)
- Basement-level windows, below-grade entries, sunken stairwells
- Downspout connections (running into ground? into sewer? disconnected?)
- Visible drainage infrastructure (French drains, catch basins, swales)
- Ground-floor HVAC equipment, electrical panels, or utilities
- Evidence of prior water damage (staining, erosion, repair patches)
- Impervious surface coverage (concrete / asphalt vs. permeable ground)
- Distance to obvious water features (canals, low-lying parks)

You will get the Street View agent's text findings below in the
'Street View Visual Analysis' section, but rely on YOUR OWN
inspection of the photo as the primary source. If you see something
the Street View agent missed, say so. If you disagree with its
assessment, explain why based on what YOU see.
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
    # image content parts go BEFORE the text part.
    user_content: list = []
    if has_image:
        user_content.append({
            "type": "image_url",
            "image_url": {"url": streetview_image_data_url},
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
        parsed["used_streetview_image"] = has_image
        return parsed

    return {
        "risk_score": 50,
        "risk_level": "medium",
        "summary": "Risk analysis returned non-JSON output; using fallback",
        "raw_response": text,
        "reasoning_trace": reasoning,
        "used_streetview_image": has_image,
    }
