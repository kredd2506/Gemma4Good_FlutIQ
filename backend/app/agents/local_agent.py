"""Local infrastructure / 311 + building-permits agent.

Currently Chicago-only. Pulls TWO Socrata signals in parallel and asks
Gemma 4 to interpret them together:

  1. 311 flood reports (WIB / SFL) within 500m / 5y — the historical
     symptom: where flooding has actually been reported.
  2. Building permits (new construction + major renovations >$100K)
     within 1km / 3y — the leading indicator: where the impervious
     surface is growing and the combined sewer load is increasing.

These signals compound. A property in a stable block with 0 311
reports is one risk profile. A property in a stable block with 0
311 reports BUT $80M of new construction permitted nearby is another
— the model can read the trajectory, not just the snapshot.

For non-Chicago cities, returns a graceful "no local dataset wired"
message so the rest of the dossier still completes.
"""
import asyncio
import json

from app.llm.client import call_gemma4, extract_text, parse_json_response
from app.llm.prompts import LOCAL_AGENT_SYSTEM_PROMPT
from app.tools.building_permits import get_nearby_construction
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
                "Chicago is the demo city for the 311 + permits signals."
            ),
            "basement_flooding_reports": 0,
            "street_flooding_reports": 0,
            "construction": {"permits_found": False},
        }

    # Two Socrata calls in parallel — same platform, different datasets.
    reports_task = asyncio.create_task(
        get_flood_reports(lat, lon, radius_m=500, years=5)
    )
    construction_task = asyncio.create_task(
        get_nearby_construction(lat, lon, radius_m=1000, years=3, min_cost=100_000)
    )
    reports, construction = await asyncio.gather(
        reports_task, construction_task, return_exceptions=False
    )

    # Sanitize construction for the prompt — drop the verbose major-projects
    # descriptions to keep the prompt tight; we'll keep the full data on
    # the agent's return for the dossier UI.
    construction_for_prompt = {
        k: v for k, v in (construction or {}).items()
        if k not in ("major_projects",)
    }
    construction_for_prompt["major_projects_count"] = len(
        (construction or {}).get("major_projects") or []
    )
    construction_for_prompt["major_projects_top3"] = [
        {
            "type": p.get("type"),
            "cost": p.get("cost"),
            "date": p.get("date"),
            "description": (p.get("description") or "")[:120],
            "address": p.get("address"),
        }
        for p in ((construction or {}).get("major_projects") or [])[:3]
    ]

    user_prompt = f"""Interpret these TWO Chicago Socrata signals together for the property at ({lat}, {lon}).

## 311 flood reports (the historical symptom)
{json.dumps(reports, indent=2, default=str)}

Context for 311:
- "WIB" = Water in Basement, "SFL" = Street Flooding
- Search radius: {reports.get('radius_m')} m, time window: {reports.get('years')} years
- Chicago combined sewer overflows after ~0.67 in/hr of rain

## Building permits (the leading indicator of impervious-surface change)
{json.dumps(construction_for_prompt, indent=2, default=str)}

Context for permits:
- New construction + major renovations within 1km, last 3 years, > $100K
- Each new structure replaces absorbent ground with roof + foundation
- Each new parking lot replaces vegetation with asphalt
- The combined sewer system serving these blocks does NOT get upgraded
  when density increases — so each new permit shifts more stormwater
  load onto the same shared pipes
- Trend "increasing" = neighborhood is actively densifying = future
  flood risk is rising even if current 311 signal is clean

Return a JSON object combining both signals with these fields:
{{
  "basement_flooding_reports": int,
  "street_flooding_reports": int,
  "total_reports": int,
  "density_assessment": "low" | "moderate" | "high",
  "pattern_notes": "1-2 sentences on the 311 recency / clustering",
  "construction": {{
    "permits_count": int,
    "new_construction_count": int,
    "total_cost": number,
    "trend_direction": "increasing" | "stable" | "decreasing",
    "interpretation": "1-2 sentences on what the development pressure means for THIS property's future flood risk — explicitly connect to impervious-surface change and the combined-sewer load",
    "concern_level": "low" | "moderate" | "high"
  }},
  "compound_signal": "1-2 sentences on how the 311 history and the permit trajectory interact — e.g. 'clean 311 today + heavy densification = rising risk' or 'high 311 + active densification = compounding risk'",
  "summary": "1 sentence for the status feed (covers BOTH signals)"
}}

Return ONLY the JSON object, no other text."""

    response = await call_gemma4(
        messages=[
            {"role": "system", "content": LOCAL_AGENT_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.2,
        max_tokens=2000,
    )

    text = extract_text(response)
    parsed = parse_json_response(text)
    if parsed:
        parsed["raw_311"] = reports
        parsed["raw_construction"] = construction
        parsed["data_available"] = True
        return parsed

    # Fallback: still return both raw signals so the UI + risk analyst
    # can see them even if Gemma's interpretation failed to parse.
    return {
        "data_available": True,
        "basement_flooding_reports": reports.get("basement_flooding", 0),
        "street_flooding_reports": reports.get("street_flooding", 0),
        "total_reports": reports.get("total_reports", 0),
        "construction": construction_for_prompt,
        "summary": (
            f"{reports.get('basement_flooding', 0)} basement + "
            f"{reports.get('street_flooding', 0)} street flood reports · "
            f"{construction_for_prompt.get('total_permits', 0)} construction "
            f"permits within 1km / 3y"
        ),
        "raw_311": reports,
        "raw_construction": construction,
        "interpretation_raw": text,
    }
