"""Weather + hydrology agent.

Fans out three free APIs in parallel — USGS stream gauges, NOAA NWS
forecasts/alerts, and Open-Meteo flood/precipitation forecast — then
asks Gemma 4 to synthesize them into a near-term flood-conditions read.
"""
import asyncio
import json

from app.llm.client import call_gemma4, extract_text, parse_json_response
from app.llm.prompts import WEATHER_AGENT_SYSTEM_PROMPT
from app.tools.noaa import get_forecast_and_alerts
from app.tools.open_meteo import get_flood_forecast
from app.tools.usgs import find_nearest_gauge, get_current_streamflow


async def _usgs_bundle(lat: float, lon: float) -> dict:
    gauge = await find_nearest_gauge(lat, lon, delta_deg=0.1)
    if not gauge:
        gauge = await find_nearest_gauge(lat, lon, delta_deg=0.3)
    if not gauge or not gauge.get("site_no"):
        return {"gauge": None, "current": None}
    try:
        current = await get_current_streamflow(gauge["site_no"])
    except Exception as e:
        current = {"error": str(e)}
    return {"gauge": gauge, "current": current}


async def run_weather_agent(lat: float, lon: float) -> dict:
    usgs_task = asyncio.create_task(_usgs_bundle(lat, lon))
    noaa_task = asyncio.create_task(get_forecast_and_alerts(lat, lon))
    om_task = asyncio.create_task(get_flood_forecast(lat, lon))

    usgs_data, noaa_data, om_data = await asyncio.gather(
        usgs_task, noaa_task, om_task, return_exceptions=True
    )

    def _safe(x):
        return {"error": str(x)} if isinstance(x, Exception) else x

    bundle = {
        "usgs": _safe(usgs_data),
        "noaa": _safe(noaa_data),
        "open_meteo": _safe(om_data),
    }

    user_prompt = f"""Interpret these hydrometeorology readings for ({lat}, {lon}):

{json.dumps(bundle, indent=2, default=str)}

Return a JSON object with:
- nearest_gauge: object with site_name, current_gage_height_ft (or null), distance_assessment ("on-site" | "nearby" | "distant" | "none")
- active_flood_alerts: list of {{event, severity, headline}} (empty list if none)
- precipitation_outlook: 1 sentence on the next 7 days of rain
- river_discharge_trend: "rising" | "steady" | "falling" | "unknown"
- near_term_concern: "low" | "moderate" | "high"
- summary: 1 sentence for the status feed

Return ONLY the JSON object, no other text."""

    response = await call_gemma4(
        messages=[
            {"role": "system", "content": WEATHER_AGENT_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.2,
    )

    text = extract_text(response)
    parsed = parse_json_response(text)
    if parsed:
        parsed["raw"] = bundle
        return parsed

    alerts = (
        bundle.get("noaa", {}).get("active_flood_alerts", [])
        if isinstance(bundle.get("noaa"), dict)
        else []
    )
    return {
        "active_flood_alerts": alerts,
        "summary": (
            f"{len(alerts)} active flood alerts" if alerts else "No active flood alerts"
        ),
        "raw": bundle,
        "interpretation_raw": text,
    }
