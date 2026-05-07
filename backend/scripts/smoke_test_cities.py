"""End-to-end smoke test for all Tier-1 cities + a graceful-degrade check.

Run:
    cd backend && set -a && source .env && set +a
    PYTHONPATH=. .venv/bin/python scripts/smoke_test_cities.py
"""
import asyncio

from app.data.cities import find_city
from app.tools.building_permits import get_nearby_construction
from app.tools.chicago_311 import get_flood_reports


TARGETS = [
    ("Chicago",       41.8127, -87.6045,  "Chicago",       "Illinois"),
    ("New York",      40.7589, -73.9851,  "New York",      "NY"),
    ("San Francisco", 37.7749, -122.4194, "San Francisco", "California"),
    ("Los Angeles",   34.0522, -118.2437, "Los Angeles",   "California"),
    ("Austin",        30.2672, -97.7431,  "Austin",        "Texas"),
    ("Atlanta",       33.7490, -84.3880,  "Atlanta",       "Georgia"),  # unsupported
]


async def main() -> None:
    for name, lat, lon, city, state in TARGETS:
        cfg = find_city(city, state)
        if cfg is None:
            print(f"\n=== {name} → unsupported (graceful degrade) ===")
            continue
        print(f"\n=== {name} ===")

        if cfg.get("311"):
            r = await get_flood_reports(cfg, lat, lon)
            if r.get("error"):
                print(f"  311 ERROR: {r['error']}")
            else:
                print(f"  311: {r.get('total_reports', 0)} reports "
                      f"(basement={r.get('basement_flooding', 0)}, "
                      f"street={r.get('street_flooding', 0)})")
        else:
            print("  311: not wired in registry")

        if cfg.get("permits"):
            p = await get_nearby_construction(cfg, lat, lon)
            if p.get("error"):
                print(f"  permits ERROR: {p['error']}")
            else:
                cost_str = (
                    f"${p.get('total_reported_cost', 0):,.0f}"
                    if p.get("has_cost") else "count-only"
                )
                print(f"  permits: {p.get('total_permits', 0)} permits, "
                      f"{p.get('new_construction_count', 0)} new, "
                      f"{cost_str}, trend={p.get('trend', {}).get('direction')}")
                top = (p.get("major_projects") or [None])[0]
                if top:
                    cost_field = (
                        f"${top.get('cost', 0):,.0f}" if top.get("cost") else ""
                    )
                    print(f"    top: {cost_field} {top.get('date', '')} "
                          f"{(top.get('address') or '')[:60]}")
        else:
            print("  permits: not wired in registry (intentional)")


if __name__ == "__main__":
    asyncio.run(main())
