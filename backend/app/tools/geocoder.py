"""Geocoding with Nominatim → US Census fallback.

Nominatim works worldwide but its US residential coverage is patchy
(many real addresses simply aren't in OSM). The US Census Geocoder
has authoritative TIGER coverage of US addresses, so we fall back
to it whenever Nominatim returns nothing.
"""
from typing import Optional

import httpx

from app.config import USER_AGENT

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
CENSUS_URL = (
    "https://geocoding.geo.census.gov/geocoder/geographies/onelineaddress"
)

# US state name → 2-letter abbrev (just enough to keep "state" useful for
# downstream agents that compare on names like "Illinois").
_US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
    "DC": "District of Columbia", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana",
    "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan",
    "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri", "MT": "Montana",
    "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey",
    "NM": "New Mexico", "NY": "New York", "NC": "North Carolina",
    "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon",
    "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah",
    "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
    "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}


async def _try_nominatim(address: str) -> Optional[dict]:
    params = {
        "q": address,
        "format": "json",
        "limit": 1,
        "addressdetails": 1,
    }
    headers = {"User-Agent": USER_AGENT}

    async with httpx.AsyncClient(timeout=15, headers=headers) as client:
        resp = await client.get(NOMINATIM_URL, params=params)
    if resp.status_code != 200:
        return None
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
        "source": "nominatim",
    }


async def _try_census(address: str) -> Optional[dict]:
    params = {
        "address": address,
        "benchmark": "Public_AR_Current",
        "vintage": "Current_Current",
        "format": "json",
    }

    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(CENSUS_URL, params=params)
    if resp.status_code != 200:
        return None

    matches = (
        resp.json().get("result", {}).get("addressMatches") or []
    )
    if not matches:
        return None

    m = matches[0]
    coords = m.get("coordinates") or {}
    components = m.get("addressComponents") or {}
    geos = m.get("geographies") or {}
    counties = geos.get("Counties") or []
    county_name = counties[0].get("NAME") if counties else ""

    state_abbrev = components.get("state") or ""
    state_full = _US_STATES.get(state_abbrev, state_abbrev)

    return {
        "lat": float(coords.get("y")),
        "lon": float(coords.get("x")),
        "display_name": m.get("matchedAddress", address),
        "city": (components.get("city") or "").title(),
        "state": state_full,
        "county": county_name,
        "source": "census",
    }


async def geocode_address(address: str) -> Optional[dict]:
    nom = await _try_nominatim(address)
    if nom:
        return nom
    return await _try_census(address)
