"""
Regional risk agent — area-level multi-hazard context.

Wraps the FEMA NRI county lookup. Asks Gemma 4 to:
  1. Identify which 2-3 hazards genuinely matter for THIS county
     (not just "all are very high" — that's true for any big-population
     county on a national-percentile-ranked index)
  2. Frame the result against the property-level flood signals the
     other agents already produced
  3. Note social vulnerability + community resilience as risk-context
     modulators, not extra hazards

The point of this agent is to broaden FlutIQ from flood-only to
"here's the multi-hazard picture of your neighborhood." Wildfire,
hurricane, earthquake, tornado are all surfaced in plain English at
the COUNTY (not address) level — exactly the resolution of FEMA's NRI.
"""
import json

from app.data.languages import prompt_directive
from app.llm.client import call_gemma4, extract_text, parse_json_response
from app.tools.nri_county import lookup_nri_county


SYSTEM_PROMPT = """You are a regional natural-hazard analyst. You read FEMA's National Risk Index (NRI) county-level data and explain in plain language which hazards meaningfully affect a specific neighborhood.

Critical guidance:
- NRI scores are NATIONAL PERCENTILES. A county at the 99th percentile for tornado risk is in the top 1% of the country for tornado risk — that's meaningful. But large-population counties tend to score Very High on many hazards just because more people + property = more expected loss; rating alone is not enough, look at the SCORES too.
- Distinguish "this county is genuinely high-risk for hazard X" (high score AND meaningful expected annual loss vs population) from "this county hits Very High because of population scale, not unusual hazard exposure."
- Cross-reference with property-level flood signals provided by other agents. NRI's Inland Flooding score is COUNTY-LEVEL; the property's actual FEMA Zone designation and 311 record are more precise.
- Social Vulnerability and Community Resilience are POPULATION-level — they describe how well the surrounding community can respond to and recover from a disaster. Note them; don't conflate with hazard exposure.
- Plain English. Avoid hazard-jargon (e.g. say "tornadoes" not "convective windstorm events").

Always respond with valid JSON only."""


async def run_regional_risk_agent(
    lat: float,
    lon: float,
    address: str,
    fema_findings: dict | None = None,
    language: str = "en",
) -> dict:
    nri = await lookup_nri_county(lat, lon)

    if not nri.get("available"):
        return {
            "available": False,
            "summary": (
                f"FEMA National Risk Index lookup unavailable: "
                f"{nri.get('error', 'unknown reason')}"
            ),
            "raw": nri,
        }

    # Trim the raw NRI for the prompt — keep top hazards + ratings only,
    # drop the long all-18-hazards array since the model already gets
    # the top 5 ranked.
    nri_for_prompt = {
        "county": nri["county"],
        "state": nri["state"],
        "population": nri.get("population"),
        "composite_risk_score": nri["composite_risk_score"],
        "composite_risk_rating": nri["composite_risk_rating"],
        "expected_annual_loss_usd": nri["expected_annual_loss_usd"],
        "social_vulnerability_rating": nri["social_vulnerability_rating"],
        "community_resilience_rating": nri["community_resilience_rating"],
        "top_hazards": nri["top_hazards"],
    }

    fema_for_prompt = (
        {k: v for k, v in (fema_findings or {}).items() if k != "raw"}
        if fema_findings else None
    )

    user_prompt = f"""Analyze the FEMA National Risk Index profile for the property's COUNTY.

Address: {address}

## NRI county-level signal
{json.dumps(nri_for_prompt, indent=2, default=str)}

## Property-level FEMA flood designation (from the property-specific FEMA agent)
{json.dumps(fema_for_prompt, indent=2, default=str) if fema_for_prompt else "(not available)"}

Return a JSON object:

{{
  "headline_hazards": [
    {{
      "name": "<short hazard name, e.g. 'Hurricane', 'Wildfire'>",
      "rating": "<copy from top_hazards above>",
      "score": <copy from top_hazards above>,
      "matters_because": "<1 sentence explaining why this hazard genuinely affects THIS county — geography, climate, history. Do not just restate the rating.>"
    }}
  ],
  "what_property_level_flood_misses": "<1-2 sentences on what the county-level NRI flood score adds vs. the property's specific FEMA Zone designation. If the FEMA agent already showed this is a SFHA property, say so. If FEMA says minimal but NRI inland-flooding is Very High, that's a meaningful gap to call out.>",
  "resilience_context": "<1-2 sentences interpreting Social Vulnerability + Community Resilience for this area, in plain English. Examples: 'Highly resilient community: well-resourced response infrastructure.' / 'Lower community resilience means a similar storm here would take longer to recover from than in a higher-resilience county.'>",
  "summary": "<1 sentence for the status feed>"
}}

CONSTRAINTS:
- headline_hazards: pick 2 to 4 hazards. Skip anything with rating "No Rating" / "Insufficient Data" / "Not Applicable".
- Don't pad with non-meaningful hazards just to fill 4 slots.
- If the county is genuinely low-risk overall (composite < 50), say so honestly.
- Return ONLY the JSON object."""

    response = await call_gemma4(
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT + prompt_directive(language)},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.2,
        max_tokens=2000,
    )

    text = extract_text(response)
    parsed = parse_json_response(text) or {}

    # Always pass through the structured NRI data so the dossier UI can
    # render the full top-hazards table even if the model's interpretation
    # truncated to 2.
    parsed["available"] = True
    parsed["nri"] = nri
    if "summary" not in parsed:
        parsed["summary"] = (
            f"County composite risk: {nri['composite_risk_rating']} "
            f"({nri['composite_risk_score']}/100)"
        )
    return parsed
