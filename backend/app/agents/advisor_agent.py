"""Advisor agent — translates risk into insurance + mitigation actions."""
import json

from app.llm.client import call_gemma4, extract_text, parse_json_response
from app.llm.prompts import ADVISOR_AGENT_SYSTEM_PROMPT


async def run_advisor_agent(all_data: dict, address: str) -> dict:
    risk = all_data.get("risk", {})
    fema = all_data.get("fema", {})
    local = all_data.get("local", {})

    user_prompt = f"""Generate flood insurance and mitigation recommendations for: {address}

## Risk Assessment
{json.dumps(risk, indent=2, default=str)}

## FEMA Designation
{json.dumps({k: v for k, v in fema.items() if k != "raw"}, indent=2, default=str)}

## Local 311 Signal
{json.dumps({k: v for k, v in local.items() if k != "raw"}, indent=2, default=str)}

Return a JSON object with:
{{
  "insurance_recommendations": [
    {{
      "policy_type": "<e.g. NFIP Preferred Risk Policy, sewer backup rider, parametric>",
      "estimated_cost": "<e.g. $400-600/yr>",
      "covers": "<what it covers>",
      "priority": "essential" | "recommended" | "optional",
      "rationale": "<1 sentence why for THIS property>"
    }}
  ],
  "mitigation_actions": [
    {{
      "action": "<e.g. Disconnect downspouts>",
      "cost": "<e.g. Free, $1K-2.5K>",
      "effort": "diy" | "contractor" | "professional",
      "impact": "low" | "medium" | "high",
      "first_step": "<a concrete first step the homeowner can take this week>"
    }}
  ],
  "key_resources": [
    {{"name": "<e.g. CNT RainReady>", "what": "<1 sentence>", "contact_or_url": "<phone or url>"}}
  ],
  "summary": "<1 sentence for the status feed>"
}}

Write at a 5th-grade reading level. No jargon without a plain-English gloss.
Return ONLY the JSON object."""

    response = await call_gemma4(
        messages=[
            {"role": "system", "content": ADVISOR_AGENT_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.3,
        max_tokens=4096,
    )

    text = extract_text(response)
    parsed = parse_json_response(text)
    if parsed:
        return parsed

    return {
        "insurance_recommendations": [],
        "mitigation_actions": [],
        "summary": "Advisor returned non-JSON output",
        "raw_response": text,
    }
