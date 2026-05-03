"""Risk-analyst agent — THE Gemma 4 reasoning showcase.

Synthesizes every data agent's output into a single risk score using
Gemma 4 with reasoning mode enabled. The reasoning trace itself is
preserved on the dossier for the writeup/demo.
"""
import json

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
) -> dict:
    user_prompt = f"""You are analyzing flood risk for: {address} ({lat}, {lon})

Here is all the data collected by our investigation team:

## FEMA Expert Findings
{json.dumps(all_data.get('fema', {}), indent=2, default=str)}

## Local Infrastructure Findings (311 data, sewer type)
{json.dumps(all_data.get('local', {}), indent=2, default=str)}

## Weather & Hydrology Findings
{json.dumps(all_data.get('weather', {}), indent=2, default=str)}

## Recent Local Flood News
{json.dumps(all_data.get('news', {}), indent=2, default=str)}

## Historical Storm Archive
{json.dumps(all_data.get('archive', {}), indent=2, default=str)}

---

TASK: Synthesize all of this data into a flood risk assessment.

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
  "key_risk_factors": ["<ranked list of top risk factors>"],
  "mitigating_factors": ["<factors that reduce risk>"],
  "summary": "<1 sentence for the status feed>"
}}

Think step by step. Show your reasoning. Return ONLY the JSON object at the end."""

    response = await call_gemma4(
        messages=[
            {"role": "system", "content": RISK_AGENT_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
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
        return parsed

    return {
        "risk_score": 50,
        "risk_level": "medium",
        "summary": "Risk analysis returned non-JSON output; using fallback",
        "raw_response": text,
        "reasoning_trace": reasoning,
    }
