"""NOAA NWS API — point forecast and active alerts. Free, no auth (UA required)."""
import httpx

from app.config import USER_AGENT

NWS_HEADERS = {"User-Agent": USER_AGENT, "Accept": "application/geo+json"}


async def get_forecast_and_alerts(lat: float, lon: float) -> dict:
    async with httpx.AsyncClient(
        timeout=20, headers=NWS_HEADERS, follow_redirects=True
    ) as client:
        # /points returns the grid metadata + forecast URL for the cell.
        points_resp = await client.get(
            f"https://api.weather.gov/points/{lat},{lon}"
        )
        if points_resp.status_code == 404:
            return {"forecast": None, "alerts": [], "note": "outside CONUS NWS coverage"}
        points_resp.raise_for_status()
        points = points_resp.json()

        forecast_url = (points.get("properties") or {}).get("forecast")
        alerts_url = f"https://api.weather.gov/alerts/active?point={lat},{lon}"

        forecast_data = None
        if forecast_url:
            try:
                f_resp = await client.get(forecast_url)
                if f_resp.status_code == 200:
                    forecast_data = f_resp.json()
            except httpx.HTTPError:
                forecast_data = None

        try:
            a_resp = await client.get(alerts_url)
            a_resp.raise_for_status()
            alerts = (a_resp.json().get("features") or [])
        except httpx.HTTPError:
            alerts = []

    # Trim forecast down to the next 5 periods to keep prompt small.
    periods = []
    if forecast_data:
        periods = (
            forecast_data.get("properties", {}).get("periods") or []
        )[:5]

    flood_alerts = [
        {
            "event": (a.get("properties") or {}).get("event"),
            "severity": (a.get("properties") or {}).get("severity"),
            "headline": (a.get("properties") or {}).get("headline"),
            "expires": (a.get("properties") or {}).get("expires"),
        }
        for a in alerts
        if "flood" in ((a.get("properties") or {}).get("event") or "").lower()
        or "flood" in ((a.get("properties") or {}).get("headline") or "").lower()
    ]

    return {
        "forecast_periods": [
            {
                "name": p.get("name"),
                "temperature": p.get("temperature"),
                "wind": p.get("windSpeed"),
                "short_forecast": p.get("shortForecast"),
                "detailed_forecast": p.get("detailedForecast"),
            }
            for p in periods
        ],
        "active_flood_alerts": flood_alerts,
        "alert_count_total": len(alerts),
    }
