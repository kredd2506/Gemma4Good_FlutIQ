"""USGS Water Services — find nearby stream gauges and current readings."""
from typing import Optional

import httpx

USGS_SITE_URL = "https://waterservices.usgs.gov/nwis/site/"
USGS_IV_URL = "https://waterservices.usgs.gov/nwis/iv/"


async def find_nearest_gauge(
    lat: float,
    lon: float,
    delta_deg: float = 0.1,
) -> Optional[dict]:
    """Return the first active stream gauge in a bounding box, or None."""
    bbox = f"{lon - delta_deg},{lat - delta_deg},{lon + delta_deg},{lat + delta_deg}"
    params = {
        "format": "rdb",
        "bBox": bbox,
        "siteType": "ST",
        "siteStatus": "active",
        "hasDataTypeCd": "iv",
    }
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(USGS_SITE_URL, params=params)

    if resp.status_code == 404:
        return None
    resp.raise_for_status()

    # RDB is a tab-separated, comment-prefixed format. Parse manually.
    site_no = None
    site_name = None
    site_lat = None
    site_lon = None
    headers: list[str] = []
    for line in resp.text.splitlines():
        if not line or line.startswith("#"):
            continue
        cols = line.split("\t")
        if not headers:
            headers = cols
            continue
        if cols[0] == "5s":  # type row, skip
            continue
        row = dict(zip(headers, cols))
        site_no = row.get("site_no") or site_no
        site_name = row.get("station_nm") or site_name
        site_lat = row.get("dec_lat_va")
        site_lon = row.get("dec_long_va")
        break

    if not site_no:
        return None

    return {
        "site_no": site_no,
        "site_name": site_name,
        "site_lat": float(site_lat) if site_lat else None,
        "site_lon": float(site_lon) if site_lon else None,
    }


async def get_current_streamflow(site_no: str) -> dict:
    """Get current discharge (00060) and gage height (00065) for a site."""
    params = {
        "format": "json",
        "sites": site_no,
        "parameterCd": "00060,00065",
        "siteStatus": "all",
    }
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(USGS_IV_URL, params=params)
    resp.raise_for_status()
    data = resp.json()

    series = data.get("value", {}).get("timeSeries", [])
    out = {"site_no": site_no, "readings": []}
    for s in series:
        var = s.get("variable", {}).get("variableName", "")
        unit = (
            s.get("variable", {}).get("unit", {}).get("unitCode", "")
        )
        values = s.get("values", [{}])[0].get("value", [])
        latest = values[-1] if values else {}
        out["readings"].append({
            "variable": var,
            "unit": unit,
            "value": latest.get("value"),
            "datetime": latest.get("dateTime"),
        })
    return out
