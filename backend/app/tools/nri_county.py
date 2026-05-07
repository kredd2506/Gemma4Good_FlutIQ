"""
FEMA National Risk Index — county-level multi-hazard scores.

Why this matters: every other agent in FlutIQ is flood-focused. NRI gives
us the calibrated, neighborhood-level "everything else" — wildfire,
hurricane, tornado, earthquake, drought, heat wave, lightning, etc., plus
Social Vulnerability and Community Resilience indices.

Source: FEMA's Resilience Analysis and Planning Tool (RAPT) hosts the
NRI Counties dataset on its public ArcGIS Online org. The FeatureServer
accepts point queries without auth — exactly what we need.

  https://services.arcgis.com/XG15cJAlne2vxtgt/arcgis/rest/services/
    National_Risk_Index_Counties/FeatureServer/0/query?...

Coverage: all 3,143 US counties + county-equivalents. Updated annually.

Each county record has 467 fields. We surface a curated subset:
  - Composite risk score + rating + percentile
  - Per-hazard score + rating for the 18 NRI hazards
  - Social Vulnerability + Community Resilience
  - Total expected annual loss in dollars

We DROP all the per-asset breakdown fields (building / population /
agriculture EAL split out across 18 hazards = 100+ columns) because
the dossier doesn't need them and they bloat the prompt budget.
"""
import json

import httpx


SERVICE_URL = (
    "https://services.arcgis.com/XG15cJAlne2vxtgt/arcgis/rest/services/"
    "National_Risk_Index_Counties/FeatureServer/0/query"
)

# 18 NRI hazards — codes used in field names + display labels.
# Order matters: most common-to-explain hazards first so any "top N"
# truncation surfaces the most-recognizable ones.
HAZARDS: list[tuple[str, str]] = [
    ("IFLD", "Inland flooding"),
    ("CFLD", "Coastal flooding"),
    ("HRCN", "Hurricane"),
    ("WFIR", "Wildfire"),
    ("ERQK", "Earthquake"),
    ("TRND", "Tornado"),
    ("HAIL", "Hail"),
    ("HWAV", "Heat wave"),
    ("CWAV", "Cold wave"),
    ("DRGT", "Drought"),
    ("WNTW", "Winter weather"),
    ("ISTM", "Ice storm"),
    ("SWND", "Strong wind"),
    ("LTNG", "Lightning"),
    ("LNDS", "Landslide"),
    ("TSUN", "Tsunami"),
    ("VLCN", "Volcanic activity"),
    ("AVLN", "Avalanche"),
]

# Order from FEMA's NRI rating bins, low → high. Used to bucket-rank.
_RATING_ORDER = (
    "Very Low",
    "Relatively Low",
    "Relatively Moderate",
    "Relatively High",
    "Very High",
    "No Rating",
    "Insufficient Data",
    "Not Applicable",
)


def _is_meaningful_rating(s: str | None) -> bool:
    if not s:
        return False
    s = s.strip()
    return s not in ("No Rating", "Insufficient Data", "Not Applicable", "")


def _rating_rank(s: str | None) -> int:
    """Rank a rating from 0 (very low) to 4 (very high). Non-rated → -1."""
    try:
        idx = _RATING_ORDER.index((s or "").strip())
        return idx if idx <= 4 else -1
    except ValueError:
        return -1


async def lookup_nri_county(lat: float, lon: float) -> dict:
    """Point query the NRI Counties FeatureServer for (lat, lon).

    Returns a dict with:
      - county / state / fips
      - composite risk: score (0-100) + rating
      - expected_annual_loss_usd
      - hazards: list of {code, name, score, rating, rank} sorted by rank desc
      - top_hazards: top 5 by rating rank (only meaningfully-rated ones)
      - social_vulnerability: rating + score
      - community_resilience: rating + score
    """
    params = {
        "geometry": json.dumps({
            "x": lon, "y": lat,
            "spatialReference": {"wkid": 4326},
        }),
        "geometryType": "esriGeometryPoint",
        "inSR": "4326",
        "outFields": "*",
        "returnGeometry": "false",
        "f": "json",
    }

    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        resp = await client.get(SERVICE_URL, params=params)

    if resp.status_code != 200:
        return {"available": False, "error": f"HTTP {resp.status_code}"}

    try:
        data = resp.json()
    except ValueError:
        return {"available": False, "error": "non-JSON response"}

    if isinstance(data, dict) and "error" in data:
        return {
            "available": False,
            "error": (data["error"].get("message") or "ArcGIS error"),
        }

    features = data.get("features") or []
    if not features:
        return {
            "available": False,
            "error": "No NRI county polygon at this point (out of US?)",
        }

    a = features[0].get("attributes") or {}

    hazards = []
    for code, name in HAZARDS:
        # NRI field naming, verified against live response 2026-05-06:
        #   _RISKR = Rating (string like "Very High")
        #   _RISKS = Score (numeric 0-100)
        #   _RISKV = Value (dollar expected loss) — not used here
        rating = a.get(f"{code}_RISKR")
        score = a.get(f"{code}_RISKS")
        if score is None and not _is_meaningful_rating(rating):
            continue
        hazards.append({
            "code": code,
            "name": name,
            "score": (
                round(float(score), 2)
                if isinstance(score, (int, float))
                else None
            ),
            "rating": rating if _is_meaningful_rating(rating) else None,
            "rank": _rating_rank(rating),
        })

    hazards_meaningful = [h for h in hazards if h["rank"] >= 0]
    hazards_meaningful.sort(
        key=lambda h: (-h["rank"], -(h["score"] or 0)),
    )
    top_hazards = hazards_meaningful[:5]

    return {
        "available": True,
        "county": a.get("COUNTY"),
        "state": a.get("STATEABBRV"),
        "state_full": a.get("STATE"),
        "fips": a.get("STCOFIPS"),
        "population": a.get("POPULATION"),
        "composite_risk_score": (
            round(float(a["RISK_SCORE"]), 2)
            if isinstance(a.get("RISK_SCORE"), (int, float)) else None
        ),
        "composite_risk_rating": a.get("RISK_RATNG"),
        "expected_annual_loss_usd": (
            int(a["EAL_VALT"])
            if isinstance(a.get("EAL_VALT"), (int, float)) else None
        ),
        "social_vulnerability_rating": a.get("SOVI_RATNG"),
        "social_vulnerability_score": (
            round(float(a["SOVI_SCORE"]), 2)
            if isinstance(a.get("SOVI_SCORE"), (int, float)) else None
        ),
        "community_resilience_rating": a.get("RESL_RATNG"),
        "community_resilience_score": (
            round(float(a["RESL_SCORE"]), 2)
            if isinstance(a.get("RESL_SCORE"), (int, float)) else None
        ),
        "hazards": hazards_meaningful,
        "top_hazards": top_hazards,
        "source": (
            "FEMA National Risk Index, county level. Hosted via FEMA's "
            "Resilience Analysis and Planning Tool (RAPT)."
        ),
    }
