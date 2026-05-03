"""Hit each data tool against a known address, report ok/fail."""
import asyncio
import json
import sys

from app.tools.chicago_311 import get_flood_reports
from app.tools.gdelt import search_flood_news
from app.tools.noaa import get_forecast_and_alerts
from app.tools.open_meteo import get_flood_forecast
from app.tools.usgs import find_nearest_gauge, get_current_streamflow

# Chicago Drexel point (Zone X, urban) — best place to test 311.
CHI_LAT, CHI_LON = 41.8127384, -87.6045491


async def run_one(name: str, coro):
    print(f"\n--- {name} ---")
    try:
        result = await coro
        s = json.dumps(result, default=str)
        print(s[:600])
        if len(s) > 600:
            print(f"...[truncated, total {len(s)} chars]")
        return True
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}")
        return False


async def main() -> int:
    results = []

    results.append(("chicago_311", await run_one(
        "chicago_311", get_flood_reports(CHI_LAT, CHI_LON)
    )))
    results.append(("noaa", await run_one(
        "noaa", get_forecast_and_alerts(CHI_LAT, CHI_LON)
    )))
    results.append(("open_meteo", await run_one(
        "open_meteo", get_flood_forecast(CHI_LAT, CHI_LON)
    )))
    results.append(("gdelt", await run_one(
        "gdelt", search_flood_news("Chicago", "Illinois")
    )))
    print("\n--- usgs ---")
    try:
        gauge = await find_nearest_gauge(CHI_LAT, CHI_LON)
        print(f"nearest gauge: {gauge}")
        if gauge and gauge.get("site_no"):
            sf = await get_current_streamflow(gauge["site_no"])
            print(f"streamflow: {json.dumps(sf, default=str)[:400]}")
            results.append(("usgs", True))
        else:
            results.append(("usgs", False))
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}")
        results.append(("usgs", False))

    print("\n=== summary ===")
    for name, ok in results:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    return 0 if all(ok for _, ok in results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
