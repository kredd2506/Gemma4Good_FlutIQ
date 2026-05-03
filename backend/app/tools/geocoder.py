"""Nominatim geocoder. Free, no API key (just User-Agent)."""
from typing import Optional

import httpx

from app.config import USER_AGENT

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"


async def geocode_address(address: str) -> Optional[dict]:
    params = {
        "q": address,
        "format": "json",
        "limit": 1,
        "addressdetails": 1,
    }
    headers = {"User-Agent": USER_AGENT}

    async with httpx.AsyncClient(timeout=15, headers=headers) as client:
        resp = await client.get(NOMINATIM_URL, params=params)
    resp.raise_for_status()
    results = resp.json()

    if not results:
        return None

    r = results[0]
    addr = r.get("address", {})
    return {
        "lat": float(r["lat"]),
        "lon": float(r["lon"]),
        "display_name": r.get("display_name", address),
        "city": addr.get("city") or addr.get("town") or addr.get("village") or "",
        "state": addr.get("state", ""),
        "county": addr.get("county", ""),
    }
