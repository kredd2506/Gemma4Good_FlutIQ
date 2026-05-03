"""FEMA expert agent.

Pattern: fetch raw NFHL data directly (no LLM needed for the lookup),
then ask Gemma 4 to interpret the data into a structured finding.
"""
import json

from app.llm.client import call_gemma4, extract_text, parse_json_response
from app.llm.prompts import FEMA_AGENT_SYSTEM_PROMPT
from app.tools.fema import lookup_fema_flood_zone


SFHA_ZONES = {"A", "AE", "AH", "AO", "AR", "A99", "V", "VE"}


async def run_fema_agent(lat: float, lon: float) -> dict:
    fema_data = await lookup_fema_flood_zone(lat, lon)

    if not fema_data:
        return {
            "flood_zone": "unknown",
            "is_sfha": False,
            "summary": "FEMA returned no data",
            "raw": fema_data,
        }

    if fema_data.get("FLD_ZONE") == "ERROR":
        return {
            "flood_zone": "error",
            "is_sfha": False,
            "summary": "FEMA query failed",
            "raw": fema_data,
        }

    user_prompt = f"""Interpret this FEMA flood zone data for coordinates ({lat}, {lon}):

{json.dumps(fema_data, indent=2, default=str)}

Return a JSON object with these fields:
- flood_zone: the zone code (e.g. "X", "AE", "VE")
- zone_description: what this zone means in plain English (1 sentence)
- is_sfha: boolean, whether this is a Special Flood Hazard Area
- requires_insurance: boolean, whether federal law mandates flood insurance
- base_flood_elevation: number or null
- map_date: the FIRM panel effective date if available, else null
- gap_warning: string or null — if the zone is X but the location is in a known urban flooding area (flat terrain, combined sewers), note that FEMA maps may not reflect actual risk
- summary: a 1-sentence finding for the status feed

Return ONLY the JSON object, no other text."""

    response = await call_gemma4(
        messages=[
            {"role": "system", "content": FEMA_AGENT_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.1,
    )

    text = extract_text(response)
    parsed = parse_json_response(text)
    if parsed:
        parsed["raw"] = fema_data
        return parsed

    zone = fema_data.get("FLD_ZONE", "unknown")
    return {
        "flood_zone": zone,
        "is_sfha": zone in SFHA_ZONES,
        "summary": f"Zone {zone}",
        "raw": fema_data,
        "interpretation_raw": text,
    }
