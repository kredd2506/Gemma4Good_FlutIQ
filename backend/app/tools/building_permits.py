"""
Chicago Building Permits via Socrata SODA API.

Why this matters for flood risk:
A property's flood risk is not static. As the surrounding block
densifies — new condos, parking lots, commercial buildings — more
absorbent ground is replaced with impervious surface. The combined
sewer system handling stormwater doesn't get upgraded; it just gets
more overwhelmed. So a house that hasn't flooded in 50 years can
suddenly be vulnerable because of what a developer built nearby.

This tool surfaces that signal: significant construction projects
(new builds + major renovations >$100K) within a configurable radius
of the property in the last few years, with cost/scale information
and a year-over-year trend.

Free dataset (`ydr8-5enu`, no auth required) — same Socrata platform
as our Chicago 311 data. Non-Chicago addresses get this from the
local_agent's graceful degrade path, so this tool is Chicago-only by
construction.
"""
from datetime import datetime, timedelta, timezone

import httpx

PERMITS_URL = "https://data.cityofchicago.org/resource/ydr8-5enu.json"


async def get_nearby_construction(
    lat: float,
    lon: float,
    radius_m: int = 1000,
    years: int = 3,
    min_cost: int = 100_000,
) -> dict:
    """Find significant construction within `radius_m` over the last `years`.

    Returns a structured dict with counts, total cost, top-5 major
    projects, and a YoY trend ("increasing" / "stable" / "decreasing").
    """
    now = datetime.now(timezone.utc)
    since = (now - timedelta(days=365 * years)).strftime("%Y-%m-%dT00:00:00")

    where = (
        "permit_type in('PERMIT - NEW CONSTRUCTION','PERMIT - RENOVATION/ALTERATION')"
        f" AND issue_date > '{since}'"
        f" AND within_circle(location, {lat}, {lon}, {radius_m})"
        f" AND reported_cost > {min_cost}"
    )
    params = {
        "$where": where,
        "$limit": 500,
        # Schema verified against the live dataset 2026-05-04: there is
        # no `suffix`, `_total_sqft`, or `community_area` column despite
        # what the source spec suggested. Reported cost is the best
        # available proxy for project scale.
        "$select": (
            "permit_type,work_description,reported_cost,issue_date,"
            "latitude,longitude,street_number,street_direction,"
            "street_name,total_fee"
        ),
        "$order": "reported_cost DESC",
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(PERMITS_URL, params=params)

    if resp.status_code != 200:
        return {
            "error": f"HTTP {resp.status_code}",
            "permits_found": False,
            "total_permits": 0,
        }

    try:
        permits = resp.json()
    except ValueError:
        return {"error": "non-JSON response", "permits_found": False, "total_permits": 0}

    if isinstance(permits, dict) and "error" in permits:
        return {
            "error": permits.get("message", "Socrata error"),
            "permits_found": False,
            "total_permits": 0,
        }

    new_construction = [
        p for p in permits if "NEW CONSTRUCTION" in (p.get("permit_type") or "")
    ]
    renovations = [
        p for p in permits if "RENOVATION" in (p.get("permit_type") or "")
    ]

    total_cost = 0.0
    for p in permits:
        try:
            total_cost += float(p.get("reported_cost") or 0)
        except (ValueError, TypeError):
            pass

    def _addr(p: dict) -> str:
        parts = [
            p.get("street_number"),
            p.get("street_direction"),
            p.get("street_name"),
        ]
        return " ".join(part for part in parts if part).strip()

    # Top 5 by reported cost (already sorted DESC by Socrata).
    major = []
    for p in permits:
        try:
            cost = float(p.get("reported_cost") or 0)
        except (ValueError, TypeError):
            continue
        if cost > 500_000:
            major.append({
                "type": "new" if "NEW CONSTRUCTION" in (p.get("permit_type") or "") else "renovation",
                "description": (p.get("work_description") or "").strip()[:200],
                "cost": cost,
                "date": (p.get("issue_date") or "")[:10],
                "address": _addr(p),
            })
        if len(major) >= 5:
            break

    # Year-over-year trend (last 12mo vs prior 12mo).
    cutoff_12 = (now - timedelta(days=365)).strftime("%Y-%m-%d")
    cutoff_24 = (now - timedelta(days=730)).strftime("%Y-%m-%d")
    last_12 = [p for p in permits if (p.get("issue_date") or "") > cutoff_12]
    prior_12 = [
        p for p in permits
        if cutoff_24 < (p.get("issue_date") or "") <= cutoff_12
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
        "permits_found": True,
        "total_permits": len(permits),
        "new_construction_count": len(new_construction),
        "renovation_count": len(renovations),
        "total_reported_cost": round(total_cost, 2),
        "major_projects": major,
        "trend": {
            "last_12_months": len(last_12),
            "prior_12_months": len(prior_12),
            "direction": direction,
        },
        "radius_m": radius_m,
        "years": years,
        "min_cost_filter": min_cost,
        "since": since,
    }
