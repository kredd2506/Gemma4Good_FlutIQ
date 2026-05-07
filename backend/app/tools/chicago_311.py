"""City 311 flood-report tool — Socrata SODA, city-aware.

Was originally chicago_311 only; now driven by the registry in
app.data.cities so any supported city can plug in without changing
caller code. The exported function name `get_flood_reports` is kept
for backward compat with the local_agent.

Each city's 311 dataset has different field names (sr_short_code in
Chicago, complaint_type in NYC, service_name in SF, sr_type_desc in
Austin) and different flood-related category VALUES. The registry
encodes both, plus the date field name and the geo column type
(some cities expose a Socrata Point column for `within_circle`,
others only have separate latitude/longitude columns and need a
bbox query instead).
"""
import math
from datetime import datetime, timedelta, timezone

import httpx


def _bbox_clause(
    lat: float,
    lon: float,
    radius_m: int,
    lat_field: str,
    lon_field: str,
    is_string: bool = False,
) -> str:
    """Build a SODA WHERE clause filtering to rows within ~radius_m of
    (lat, lon) using a lat/lon bounding box. When `is_string=True` the
    fields are wrapped in `to_number()` because some cities (NYC DOB,
    LA building permits) store lat/lon as text rather than numeric."""
    lat_deg = radius_m / 111_000
    lon_deg = radius_m / (111_000 * max(0.1, math.cos(math.radians(lat))))
    # SoQL doesn't have to_number(); use PostgreSQL :: cast syntax for
    # cities that store lat/lon as text (NYC DOB, LA building permits).
    lf = f"{lat_field}::number" if is_string else lat_field
    lnf = f"{lon_field}::number" if is_string else lon_field
    return (
        f"{lf} >= {lat - lat_deg} AND {lf} <= {lat + lat_deg} "
        f"AND {lnf} >= {lon - lon_deg} AND {lnf} <= {lon + lon_deg}"
    )


async def get_flood_reports(
    config: dict,
    lat: float,
    lon: float,
    radius_m: int = 500,
    years: int = 5,
) -> dict:
    """Fetch flood-related 311 reports near a location for the given city
    config. Returns a dict ready for the local_agent to interpret.

    The shape of the return is intentionally Chicago-shaped (basement /
    street counts) so the rest of the pipeline doesn't have to change —
    cities without that distinction surface under "total_reports".
    """
    cfg = config.get("311") if config else None
    if not cfg:
        return {
            "city": (config or {}).get("name", ""),
            "supported": False,
            "total_reports": 0,
            "basement_flooding": 0,
            "street_flooding": 0,
            "recent_reports": [],
            "radius_m": radius_m,
            "years": years,
        }

    since = (
        datetime.now(timezone.utc) - timedelta(days=365 * years)
    ).strftime("%Y-%m-%dT00:00:00")

    date_field = cfg["date_field"]
    cat_clause = cfg["category_in_clause"]
    location_field = cfg.get("location_field")

    # Some cities have a Socrata Point column → within_circle. Others only
    # expose lat/lon scalars → bbox.
    if location_field:
        geo_clause = f"within_circle({location_field}, {lat}, {lon}, {radius_m})"
    else:
        geo_clause = _bbox_clause(
            lat, lon, radius_m,
            cfg.get("lat_field", "latitude"),
            cfg.get("lon_field", "longitude"),
            is_string=cfg.get("lat_lon_is_string", False),
        )

    where = f"{cat_clause} AND {date_field} > '{since}' AND ({geo_clause})"
    params = {
        "$where": where,
        "$limit": 1000,
        "$select": cfg["select_fields"],
        "$order": f"{date_field} DESC",
    }

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        resp = await client.get(cfg["url"], params=params)

    if resp.status_code != 200:
        return {
            "city": config["name"],
            "supported": True,
            "error": f"HTTP {resp.status_code}",
            "total_reports": 0,
            "basement_flooding": 0,
            "street_flooding": 0,
            "recent_reports": [],
            "radius_m": radius_m,
            "years": years,
        }

    try:
        reports = resp.json()
    except ValueError:
        return {
            "city": config["name"],
            "supported": True,
            "error": "non-JSON response",
            "total_reports": 0,
            "basement_flooding": 0,
            "street_flooding": 0,
            "recent_reports": [],
            "radius_m": radius_m,
            "years": years,
        }

    # Heuristically split into "basement-flavored" vs "street-flavored"
    # 311 reports for cities that surface that distinction. Chicago has
    # explicit codes (WIB / SFL); other cities have to be inferred from
    # the category value and descriptor.
    cat_field = cfg["category_field"]
    basement_keywords = ("WIB", "Sewer", "basement", "Basement")
    street_keywords = ("SFL", "Street", "Drain", "Storm", "Flooding")

    basement = []
    street = []
    for r in reports:
        cat = (r.get(cat_field) or "")
        descr = " ".join(str(v) for v in r.values()).lower()
        if any(k in cat for k in basement_keywords) or "basement" in descr:
            basement.append(r)
        elif any(k in cat for k in street_keywords):
            street.append(r)
        else:
            street.append(r)  # default bucket

    return {
        "city": config["name"],
        "supported": True,
        "total_reports": len(reports),
        "basement_flooding": len(basement),
        "street_flooding": len(street),
        "radius_m": radius_m,
        "years": years,
        "since": since,
        "recent_reports": reports[:10],
        "category_field": cat_field,
        "categories_queried": list(cfg["flood_categories"]),
    }
