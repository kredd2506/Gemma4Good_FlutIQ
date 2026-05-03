"""Open-Meteo flood + precipitation forecast. Free, no auth."""
import httpx

FLOOD_URL = "https://flood-api.open-meteo.com/v1/flood"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"


async def get_flood_forecast(lat: float, lon: float) -> dict:
    flood_params = {
        "latitude": lat,
        "longitude": lon,
        "daily": "river_discharge,river_discharge_max",
        "past_days": 30,
        "forecast_days": 7,
    }
    precip_params = {
        "latitude": lat,
        "longitude": lon,
        "daily": "precipitation_sum,precipitation_hours,precipitation_probability_max",
        "forecast_days": 7,
        "timezone": "auto",
    }

    async with httpx.AsyncClient(timeout=20) as client:
        flood_resp = await client.get(FLOOD_URL, params=flood_params)
        precip_resp = await client.get(FORECAST_URL, params=precip_params)

    flood: dict = {}
    if flood_resp.status_code == 200:
        flood = flood_resp.json()
    precip: dict = {}
    if precip_resp.status_code == 200:
        precip = precip_resp.json()

    return {
        "flood": flood.get("daily") or {},
        "precipitation": precip.get("daily") or {},
    }
