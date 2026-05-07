"""Local infrastructure agent — 311 + building permits, city-aware.

Now driven by the registry in app.data.cities. For any supported city
we run the two Socrata signals in parallel and ask Gemma 4 to interpret
them together, with city-specific context (combined-vs-separated
sewers, dominant flood mode, local hazard pattern) injected into the
prompt so the reasoning is calibrated to the right system.

Honest about per-city data quality:
  - Cities with both signals (Chicago, NYC, SF, Austin) get the full
    "compound signal" narrative.
  - Cities with only one signal (LA: permits-only) get a partial
    narrative that explicitly says what's missing.
  - Cities not in the registry get a clean "not supported here"
    summary so the rest of the dossier still completes.
"""
import asyncio
import json

from app.data.cities import find_city
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
    cfg = find_city(city, state)

    if cfg is None:
        return {
            "city": city,
            "data_available": False,
            "summary": (
                f"No local-data integration wired for {city or 'this location'}; "
                "Tier 1 cities are Chicago, NYC, San Francisco, Los Angeles, Austin."
            ),
            "basement_flooding_reports": 0,
            "street_flooding_reports": 0,
            "construction": {"permits_found": False},
        }

    has_311 = cfg.get("311") is not None
    has_permits = cfg.get("permits") is not None

    # Run whichever signals this city actually has, in parallel.
    tasks = []
    if has_311:
        tasks.append(("reports", asyncio.create_task(
            get_flood_reports(cfg, lat, lon, radius_m=500, years=5)
        )))
    if has_permits:
        tasks.append(("construction", asyncio.create_task(
            get_nearby_construction(cfg, lat, lon, radius_m=1000, years=3, min_cost=100_000)
        )))
    results: dict = {}
    for name, t in tasks:
        try:
            results[name] = await t
        except Exception as e:
            results[name] = {"error": f"{type(e).__name__}: {str(e)[:100]}"}

    reports = results.get("reports") or {}
    construction = results.get("construction") or {}

    # Trim construction for the prompt — don't dump 5 long descriptions
    # into the system; we keep the full data on the agent's return for
    # the dossier UI to render.
    construction_for_prompt = {
        k: v for k, v in construction.items() if k not in ("major_projects",)
    }
    construction_for_prompt["major_projects_count"] = len(
        construction.get("major_projects") or []
    )
    construction_for_prompt["major_projects_top3"] = [
        {
            "type": p.get("type"),
            "cost": p.get("cost"),
            "date": p.get("date"),
            "description": (p.get("description") or "")[:120],
            "address": p.get("address"),
        }
        for p in (construction.get("major_projects") or [])[:3]
    ]

    has_cost = construction.get("has_cost", False)
    cost_note = (
        ""
        if has_cost
        else (
            "NOTE: this city's permits dataset does NOT expose project cost. "
            "Reason about permit COUNT, project type, and trend direction — "
            "do NOT report dollar amounts you don't actually have."
        )
    )

    user_prompt = f"""You are interpreting LOCAL infrastructure signals for a property in {cfg['name']} ({lat}, {lon}).

City context (use this to calibrate your reasoning):
{cfg['context_blurb']}

## 311 service-request signal — historical symptom
{f"Available for {cfg['name']}" if has_311 else "NOT AVAILABLE for this city — skip 311 reasoning."}
{json.dumps(reports, indent=2, default=str) if has_311 else ""}

## Building permits signal — leading indicator of impervious-surface change
{f"Available for {cfg['name']}" if has_permits else "NOT AVAILABLE for this city — skip permit reasoning."}
{json.dumps(construction_for_prompt, indent=2, default=str) if has_permits else ""}
{cost_note}

Return a JSON object combining whatever signals were available with these fields:
{{
  "basement_flooding_reports": int,
  "street_flooding_reports": int,
  "total_reports": int,
  "density_assessment": "low" | "moderate" | "high" | "n/a",
  "pattern_notes": "1-2 sentences on the 311 pattern, or 'No 311 signal available for this city.'",
  "construction": {{
    "permits_count": int,
    "new_construction_count": int,
    "total_cost": number_or_null,
    "trend_direction": "increasing" | "stable" | "decreasing",
    "interpretation": "1-2 sentences on what the development pressure means for THIS property's future flood risk in THIS city's drainage system",
    "concern_level": "low" | "moderate" | "high"
  }},
  "compound_signal": "1-2 sentences on how the available signals interact for {cfg['name']} specifically. If only one signal is available, say so explicitly.",
  "summary": "1 sentence for the status feed"
}}

Return ONLY the JSON object."""

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
        parsed["raw_311"] = reports if has_311 else {"supported": False}
        parsed["raw_construction"] = construction if has_permits else {"supported": False}
        parsed["data_available"] = True
        parsed["city_supported"] = True
        parsed["city_id"] = cfg["id"]
        parsed["has_311"] = has_311
        parsed["has_permits"] = has_permits
        parsed["has_permit_cost"] = has_cost
        return parsed

    # Fallback if Gemma's JSON didn't parse — still return the raw signals
    # so the dossier shows something useful.
    return {
        "data_available": True,
        "city_supported": True,
        "city_id": cfg["id"],
        "has_311": has_311,
        "has_permits": has_permits,
        "has_permit_cost": has_cost,
        "basement_flooding_reports": reports.get("basement_flooding", 0),
        "street_flooding_reports": reports.get("street_flooding", 0),
        "total_reports": reports.get("total_reports", 0),
        "construction": construction_for_prompt,
        "summary": (
            f"{reports.get('basement_flooding', 0)} basement + "
            f"{reports.get('street_flooding', 0)} street flood reports · "
            f"{construction.get('total_permits', 0)} construction permits "
            f"within 1km / 3y in {cfg['name']}"
        ),
        "raw_311": reports,
        "raw_construction": construction,
        "interpretation_raw": text,
    }
