"""
City building-permits tool — Socrata SODA, city-aware.

Was originally Chicago-only; now driven by app.data.cities so any
supported city can plug in. The exported function name
`get_nearby_construction` is preserved so callers don't change.

Honest about per-city data quality:
  - Some cities (Chicago, SF, LA, Dallas) expose a project cost
    field — the dossier can show '$80M new medical office'.
  - Other cities (NYC DOB, Austin) don't expose cost in their
    public dataset — the dossier degrades to permit COUNT and
    project type narrative ('14 new buildings, increasing trend').

Each city's config encodes the right field names for permit_type,
cost (if any), date, and the geo column type (Socrata Point column
for `within_circle` vs. bbox-on-lat/lon for cities without one).
"""
import math
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx


def _bbox_clause(
    lat: float,
    lon: float,
    radius_m: int,
    lat_field: str,
    lon_field: str,
    is_string: bool = False,
) -> str:
    """SODA WHERE fragment that bounds rows within ~radius_m of (lat, lon).
    When `is_string=True` (NYC DOB, LA permits) the fields get wrapped in
    `to_number()` because the dataset stores lat/lon as text."""
    lat_deg = radius_m / 111_000
    lon_deg = radius_m / (111_000 * max(0.1, math.cos(math.radians(lat))))
    # SoQL doesn't have to_number(); use PostgreSQL :: cast for cities
    # that store lat/lon as text.
    lf = f"{lat_field}::number" if is_string else lat_field
    lnf = f"{lon_field}::number" if is_string else lon_field
    return (
        f"{lf} >= {lat - lat_deg} AND {lf} <= {lat + lat_deg} "
        f"AND {lnf} >= {lon - lon_deg} AND {lnf} <= {lon + lon_deg}"
    )


def _coerce_float(v) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


async def get_nearby_construction(
    config: dict,
    lat: float,
    lon: float,
    radius_m: int = 1000,
    years: int = 3,
    min_cost: int = 100_000,
) -> dict:
    """Fetch significant construction permits near a location for a city.

    Returns the same shape regardless of city, with `has_cost` flagging
    whether the dollar-amount narrative is meaningful for this city.
    """
    cfg = (config or {}).get("permits")
    if not cfg:
        return {
            "permits_found": False,
            "supported": False,
            "total_permits": 0,
            "city": (config or {}).get("name", ""),
        }

    since = (
        datetime.now(timezone.utc) - timedelta(days=365 * years)
    ).strftime("%Y-%m-%dT00:00:00")

    type_field = cfg["permit_type_field"]
    type_values = cfg["permit_type_values"]
    type_clause = " OR ".join(f"{type_field}='{v}'" for v in type_values)

    cost_field = cfg.get("cost_field")
    has_cost = bool(cost_field and cfg.get("has_cost"))

    location_field = cfg.get("location_field")
    if location_field:
        geo_clause = f"within_circle({location_field}, {lat}, {lon}, {radius_m})"
    else:
        geo_clause = _bbox_clause(
            lat, lon, radius_m,
            cfg.get("lat_field", "latitude"),
            cfg.get("lon_field", "longitude"),
            is_string=cfg.get("lat_lon_is_string", False),
        )

    where_parts = [
        f"({type_clause})",
        f"{cfg['date_field']} > '{since}'",
        f"({geo_clause})",
    ]
    if has_cost and min_cost:
        # Some cities (SF) store cost as text — apply same :: cast as for lat/lon.
        cost_expr = (
            f"{cost_field}::number"
            if cfg.get("cost_is_string")
            else cost_field
        )
        where_parts.append(f"{cost_expr} > {min_cost}")

    params = {
        "$where": " AND ".join(where_parts),
        "$limit": 500,
        "$select": cfg["select_fields"],
        "$order": f"{cost_field} DESC" if has_cost else f"{cfg['date_field']} DESC",
    }

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        resp = await client.get(cfg["url"], params=params)

    if resp.status_code != 200:
        return {
            "city": config["name"],
            "supported": True,
            "error": f"HTTP {resp.status_code}",
            "permits_found": False,
            "total_permits": 0,
            "has_cost": has_cost,
        }

    try:
        permits = resp.json()
    except ValueError:
        return {
            "city": config["name"],
            "supported": True,
            "error": "non-JSON response",
            "permits_found": False,
            "total_permits": 0,
            "has_cost": has_cost,
        }

    if isinstance(permits, dict) and "error" in permits:
        return {
            "city": config["name"],
            "supported": True,
            "error": permits.get("message", "Socrata error"),
            "permits_found": False,
            "total_permits": 0,
            "has_cost": has_cost,
        }

    new_marker = cfg.get("new_construction_marker", "")
    reno_marker = cfg.get("renovation_marker", "")

    new_construction = []
    renovations = []
    for p in permits:
        ptype = (p.get(type_field) or "")
        if new_marker and new_marker in ptype:
            new_construction.append(p)
        elif reno_marker and reno_marker in ptype:
            renovations.append(p)
        else:
            renovations.append(p)

    total_cost = 0.0
    for p in permits:
        c = _coerce_float(p.get(cost_field) if cost_field else None)
        if c:
            total_cost += c

    address_keys = cfg.get("address_keys") or ()

    def _addr(p: dict) -> str:
        parts = [p.get(k) for k in address_keys]
        return " ".join(str(part) for part in parts if part).strip()

    # Top 5 — by cost if we have it, else by date.
    major = []
    for p in permits:
        cost = _coerce_float(p.get(cost_field) if cost_field else None) or 0.0
        if has_cost and cost <= 500_000:
            continue
        ptype = p.get(type_field) or ""
        major.append({
            "type": "new" if (new_marker and new_marker in ptype) else "renovation",
            "description": (
                p.get("work_description") or p.get("description") or p.get("work_desc") or ""
            ).strip()[:200],
            "cost": cost if has_cost else None,
            "date": (
                p.get(cfg["date_field"]) or ""
            )[:10],
            "address": _addr(p),
        })
        if len(major) >= 5:
            break

    # Year-over-year trend (last 12mo vs prior 12mo)
    now = datetime.now(timezone.utc)
    cutoff_12 = (now - timedelta(days=365)).strftime("%Y-%m-%d")
    cutoff_24 = (now - timedelta(days=730)).strftime("%Y-%m-%d")
    last_12 = [p for p in permits if (p.get(cfg["date_field"]) or "") > cutoff_12]
    prior_12 = [
        p for p in permits
        if cutoff_24 < (p.get(cfg["date_field"]) or "") <= cutoff_12
    ]

    if len(prior_12) == 0:
        direction = "increasing" if len(last_12) > 0 else "stable"
    elif len(last_12) > len(prior_12) * 1.2:
        direction = "increasing"
    elif len(last_12) < len(prior_12) * 0.8:
        direction = "decreasing"
    else:
        direction = "stable"

    return {
        "city": config["name"],
        "supported": True,
        "permits_found": True,
        "has_cost": has_cost,
        "total_permits": len(permits),
        "new_construction_count": len(new_construction),
        "renovation_count": len(renovations),
        "total_reported_cost": round(total_cost, 2) if has_cost else None,
        "major_projects": major,
        "trend": {
            "last_12_months": len(last_12),
            "prior_12_months": len(prior_12),
            "direction": direction,
        },
        "radius_m": radius_m,
        "years": years,
        "min_cost_filter": min_cost if has_cost else None,
        "since": since,
    }
