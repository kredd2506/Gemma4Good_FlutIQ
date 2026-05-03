"""Advisor agent — translates risk into insurance + mitigation actions.

Uses a curated catalog of REAL insurance products and city-specific
resources (see app.data.insurance_catalog). Gemma 4's job is to pick
which catalog entries fit this property and write the plain-English
rationale — not to invent product names or prices.
"""
import json

from app.data.insurance_catalog import (
    products_available_in,
    resources_for_city,
)
from app.llm.client import call_gemma4, extract_text, parse_json_response
from app.llm.prompts import ADVISOR_AGENT_SYSTEM_PROMPT


_STATE_TO_CODE = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT",
    "delaware": "DE", "district of columbia": "DC", "florida": "FL",
    "georgia": "GA", "hawaii": "HI", "idaho": "ID", "illinois": "IL",
    "indiana": "IN", "iowa": "IA", "kansas": "KS", "kentucky": "KY",
    "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN",
    "mississippi": "MS", "missouri": "MO", "montana": "MT",
    "nebraska": "NE", "nevada": "NV", "new hampshire": "NH",
    "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
    "north carolina": "NC", "north dakota": "ND", "ohio": "OH",
    "oklahoma": "OK", "oregon": "OR", "pennsylvania": "PA",
    "rhode island": "RI", "south carolina": "SC", "south dakota": "SD",
    "tennessee": "TN", "texas": "TX", "utah": "UT", "vermont": "VT",
    "virginia": "VA", "washington": "WA", "west virginia": "WV",
    "wisconsin": "WI", "wyoming": "WY",
}


async def run_advisor_agent(all_data: dict, address: str) -> dict:
    risk = all_data.get("risk", {}) or {}
    fema = all_data.get("fema", {}) or {}
    local = all_data.get("local", {}) or {}

    geo = all_data.get("_geo", {}) or {}
    city = geo.get("city", "") or ""
    state = geo.get("state", "") or ""
    state_code = _STATE_TO_CODE.get(state.lower(), "")

    products = products_available_in(state_code)
    resources = resources_for_city(city)

    catalog_for_prompt = [
        {
            "id": p["id"],
            "name": p["name"],
            "kind": p["kind"],
            "typical_cost": p.get("typical_cost"),
            "cost_note": p.get("cost_note"),
            "covers": p["covers"],
            "does_not_cover": p["does_not_cover"],
            "how_to_buy": p["how_to_buy"],
            "fits_when": p["fits_when"],
        }
        for p in products
    ]

    user_prompt = f"""Generate flood insurance and mitigation guidance for: {address}
City: {city or "(unknown)"} · State: {state or "(unknown)"}

## Risk assessment
{json.dumps(risk, indent=2, default=str)}

## FEMA designation
{json.dumps({k: v for k, v in fema.items() if k != "raw"}, indent=2, default=str)}

## Local 311 signal
{json.dumps({k: v for k, v in local.items() if k != "raw"}, indent=2, default=str)}

## CATALOG of real, verified insurance products (USE ONLY THESE)
{json.dumps(catalog_for_prompt, indent=2)}

## Verified local + nationwide resources (pass through unchanged)
{json.dumps(resources, indent=2)}

---

TASK: Pick which catalog products genuinely fit THIS property based on its
risk profile, FEMA zone, and 311 signal. For each one you pick, write a
short rationale that explains why it fits THIS address (not a generic pitch).

Return a JSON object with:
{{
  "tldr": "<1-2 sentences a homeowner can act on today, no jargon>",
  "insurance_recommendations": [
    {{
      "product_id": "<must match an id from the catalog>",
      "policy_type": "<the catalog 'name' field, copied verbatim>",
      "estimated_cost": "<the catalog 'typical_cost' field, copied verbatim>",
      "covers": "<the catalog 'covers' field, copied verbatim>",
      "does_not_cover": "<the catalog 'does_not_cover' field, copied verbatim>",
      "how_to_buy": "<the catalog 'how_to_buy' field, copied verbatim>",
      "priority": "start_here" | "also_consider" | "only_if",
      "rationale": "<2 sentences specific to THIS property — why this fits, in plain English>"
    }}
  ],
  "mitigation_actions": [
    {{
      "action": "<short title, e.g. Disconnect downspouts>",
      "cost": "<e.g. Free, $150-300, $1K-2.5K>",
      "effort": "diy" | "contractor" | "professional",
      "impact": "low" | "medium" | "high",
      "first_step": "<a concrete first step the homeowner can take this week>"
    }}
  ],
  "key_resources": <COPY THE PROVIDED resources LIST ABOVE VERBATIM>,
  "summary": "<1 sentence for the status feed>"
}}

CRITICAL: every insurance_recommendations entry MUST have a product_id that
exists in the catalog above. Do not add products that aren't in the catalog.
Do not invent prices or company names. Return ONLY the JSON object."""

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
    if not parsed:
        return {
            "tldr": "",
            "insurance_recommendations": [],
            "mitigation_actions": [],
            "key_resources": resources,
            "summary": "Advisor returned non-JSON output",
            "raw_response": text,
        }

    # Force key_resources to the verified list — don't trust the model.
    parsed["key_resources"] = resources
    # Drop any insurance entries that don't reference a real catalog id.
    valid_ids = {p["id"] for p in products}
    cleaned = []
    for rec in parsed.get("insurance_recommendations") or []:
        if rec.get("product_id") in valid_ids:
            cleaned.append(rec)
    parsed["insurance_recommendations"] = cleaned

    return parsed
