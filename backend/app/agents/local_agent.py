"""Local infrastructure / 311 agent.

Currently Chicago-only — uses the 311 sewer-backup signal as a proxy
for combined-sewer urban flooding risk. For non-Chicago cities, returns
a graceful "no local dataset wired" message so the rest of the dossier
still completes.
"""
import json

from app.llm.client import call_gemma4, extract_text, parse_json_response
from app.llm.prompts import LOCAL_AGENT_SYSTEM_PROMPT
from app.tools.chicago_311 import get_flood_reports


async def run_local_agent(
    lat: float,
    lon: float,
    city: str,
    state: str,
) -> dict:
    is_chicago = (
        city.lower() == "chicago" or "chicago" in city.lower()
    ) and state.lower() in ("illinois", "il")

    if not is_chicago:
        return {
            "city": city,
            "data_available": False,
            "summary": (
                f"No local-311 dataset wired for {city or 'this location'}; "
                "Chicago is the demo city for the 311 sewer-backup signal."
            ),
            "basement_flooding_reports": 0,
            "street_flooding_reports": 0,
        }

    reports = await get_flood_reports(lat, lon, radius_m=500, years=5)

    user_prompt = f"""Interpret this Chicago 311 flood-report data for the property at ({lat}, {lon}):

{json.dumps(reports, indent=2, default=str)}

Context:
- "WIB" = Water in Basement, "SFL" = Street Flooding
- These are the two 311 codes that signal urban / combined-sewer flooding
- Search radius: {reports['radius_m']} m, time window: {reports['years']} years
- Chicago combined sewer overflows after ~0.67 in/hr of rain

Return a JSON object with these fields:
- basement_flooding_reports: int
- street_flooding_reports: int
- total_reports: int
- density_assessment: "low" | "moderate" | "high" — interpret given the radius and years
- pattern_notes: 1-2 sentences on what the recency/clustering implies
- summary: 1 sentence for the status feed

Return ONLY the JSON object, no other text."""

    response = await call_gemma4(
        messages=[
            {"role": "system", "content": LOCAL_AGENT_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.2,
    )

    text = extract_text(response)
    parsed = parse_json_response(text)
    if parsed:
        parsed["raw"] = reports
        parsed["data_available"] = True
        return parsed

    return {
        "data_available": True,
        "basement_flooding_reports": reports["basement_flooding"],
        "street_flooding_reports": reports["street_flooding"],
        "total_reports": reports["total_reports"],
        "summary": (
            f"{reports['basement_flooding']} basement + "
            f"{reports['street_flooding']} street flood reports in 5y / 500m"
        ),
        "raw": reports,
        "interpretation_raw": text,
    }
