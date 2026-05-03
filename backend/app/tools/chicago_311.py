"""Chicago 311 service requests via Socrata SODA API. Free, no auth."""
from datetime import datetime, timedelta, timezone

import httpx

# v6vf-nfxy is the unified 311 service requests dataset.
CHICAGO_311_URL = "https://data.cityofchicago.org/resource/v6vf-nfxy.json"

# WIB = Water in Basement, SFL = Street Flooding (these are the
# Chicago 311 sr_short_codes that signal urban flooding).
FLOOD_CODES = ("WIB", "SFL")


async def get_flood_reports(
    lat: float,
    lon: float,
    radius_m: int = 500,
    years: int = 5,
) -> dict:
    since = (
        datetime.now(timezone.utc) - timedelta(days=365 * years)
    ).strftime("%Y-%m-%dT00:00:00")

    codes = ",".join(f"'{c}'" for c in FLOOD_CODES)
    where = (
        f"sr_short_code in({codes}) "
        f"AND created_date > '{since}' "
        f"AND within_circle(location, {lat}, {lon}, {radius_m})"
    )
    params = {
        "$where": where,
        "$limit": 1000,
        "$select": "sr_short_code,created_date,street_address,ward",
        "$order": "created_date DESC",
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(CHICAGO_311_URL, params=params)
    resp.raise_for_status()
    reports = resp.json()

    basement = [r for r in reports if r.get("sr_short_code") == "WIB"]
    street = [r for r in reports if r.get("sr_short_code") == "SFL"]

    return {
        "total_reports": len(reports),
        "basement_flooding": len(basement),
        "street_flooding": len(street),
        "radius_m": radius_m,
        "years": years,
        "since": since,
        "recent_reports": reports[:10],
    }
