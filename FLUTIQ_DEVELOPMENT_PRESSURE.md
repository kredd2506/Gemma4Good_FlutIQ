# FlutIQ — Development-Induced Flooding Feature

## The insight

Your flood risk isn't static. It changes based on what your neighbors build.

New construction replaces absorbent soil with impervious surface. A house
that hasn't flooded in 50 years can suddenly be underwater because of a
new parking lot, condo building, or commercial development nearby. The
combined sewer system doesn't get upgraded when density increases — it
just gets more overwhelmed.

**This is data nobody shows homeowners.** And it's freely available.

---

## The data: Chicago Building Permits (Socrata)

**Endpoint:** `https://data.cityofchicago.org/resource/ydr8-5enu.json`
**Auth:** None (optional app token)
**Format:** Same Socrata SODA pattern as the 311 data you already use

### Key fields

| Field | What it tells you |
|-------|-------------------|
| `permit_type` | `PERMIT - NEW CONSTRUCTION`, `PERMIT - RENOVATION/ALTERATION`, `PERMIT - WRECKING/DEMOLITION` |
| `work_description` | Free text — "NEW 5 STORY 24 UNIT RESIDENTIAL BUILDING", "CONSTRUCT NEW PARKING LOT", "NEW COMMERCIAL BUILDING" |
| `reported_cost` | Dollar value — a $5M new construction is a major impervious surface addition |
| `issue_date` | When the permit was issued |
| `latitude`, `longitude` | Geocoded location |
| `community_area` | Chicago community area name |
| `_total_sqft` | Total square footage (when available) |
| `_total_fee` | Permit fee (proxy for project scale) |

### The query you need

Find new construction and major renovations within 1km of the property
in the last 3 years:

```
GET https://data.cityofchicago.org/resource/ydr8-5enu.json
  ?$where=permit_type in('PERMIT - NEW CONSTRUCTION', 'PERMIT - RENOVATION/ALTERATION')
    AND issue_date > '2023-01-01'
    AND within_circle(location, {lat}, {lon}, 1000)
    AND reported_cost > 100000
  &$limit=500
  &$select=permit_type,work_description,reported_cost,issue_date,
           latitude,longitude,street_number,street_direction,
           street_name,suffix,_total_sqft
  &$order=reported_cost DESC
```

This gives you: every significant construction project within 1km of
the property in the last 3 years, sorted by cost (biggest projects first).

---

## What this reveals for flood risk

### Signal 1: Net impervious surface increase

- Count new construction permits within 1km
- Sum the total square footage of new buildings
- Flag any large-footprint projects ($500K+, commercial, multi-unit)
- **Gemma 4 reads:** "In the last 3 years, 8 new construction permits have been issued within 1km, including a 24-unit residential building (12,000 sq ft footprint) and a new parking structure. This represents an estimated 25,000+ sq ft of new impervious surface, increasing stormwater runoff into an already-stressed combined sewer system."

### Signal 2: Demolition without replacement (vacant lots = absorption capacity)

- `PERMIT - WRECKING/DEMOLITION` permits create temporary permeable lots
- But if followed by new construction, the net effect is often MORE impervious surface (larger footprint building replacing smaller one)
- **Gemma 4 reads:** "Two demolition permits followed by new construction permits at the same addresses indicate densification — smaller structures replaced by larger ones with greater lot coverage."

### Signal 3: Development velocity / trend

- Compare permit counts: last 12 months vs. prior 24 months
- Increasing construction activity = increasing future impervious surface = increasing future flood risk
- **Gemma 4 reads:** "New construction permit activity within 1km has increased 40% year-over-year (12 permits in 2025 vs. 8 in 2024), suggesting ongoing densification that will continue to increase stormwater load."

### Signal 4: Large commercial / institutional projects

- Filter for `reported_cost > 1000000`
- These are the "concrete funnel" projects: shopping centers, parking structures, institutional buildings
- A single $10M project can add more impervious surface than 20 residential renovations
- **Gemma 4 reads:** "A $3.2M commercial construction project was permitted 600m northwest of the property in March 2025. Projects of this scale typically add 5,000-15,000 sq ft of impervious surface."

---

## How this integrates with the satellite image

This is where the multi-image reasoning gets really powerful:

The satellite image shows the *current* impervious surface. The building
permits data shows the *trajectory* — what's being built right now and
what the neighborhood will look like in 1-2 years.

The risk analyst's reasoning trace can say:

> "The satellite view shows this block is currently ~75% impervious surface.
> But the building permits data reveals 8 new construction projects within
> 1km in the last 3 years, including a 24-unit residential building 400m
> north. This neighborhood is actively densifying. Even if the property's
> flood risk is moderate today, the trend is toward higher risk as more
> absorbent ground is replaced with concrete and rooftop."

That's a **temporal + spatial + visual** argument. No existing flood
risk tool makes this connection.

---

## Implementation

### New tool: `backend/app/tools/building_permits.py`

```python
import httpx
from datetime import datetime, timedelta

PERMITS_URL = "https://data.cityofchicago.org/resource/ydr8-5enu.json"

async def get_nearby_construction(
    lat: float,
    lon: float,
    radius_m: int = 1000,
    years: int = 3,
    min_cost: int = 100000,
) -> dict:
    """
    Find significant construction activity near the property.
    Chicago only (same Socrata platform as 311).
    Returns: count, total cost, major projects, trend.
    """
    since = (datetime.now() - timedelta(days=365 * years)).strftime("%Y-%m-%dT00:00:00")
    
    query = (
        f"$where=permit_type in("
        f"'PERMIT - NEW CONSTRUCTION',"
        f"'PERMIT - RENOVATION/ALTERATION'"
        f") AND issue_date > '{since}'"
        f" AND within_circle(location, {lat}, {lon}, {radius_m})"
        f" AND reported_cost > {min_cost}"
        f"&$limit=500"
        f"&$select=permit_type,work_description,reported_cost,"
        f"issue_date,latitude,longitude,street_number,"
        f"street_direction,street_name,suffix,_total_sqft"
        f"&$order=reported_cost DESC"
    )
    
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(f"{PERMITS_URL}?{query}")
        permits = resp.json()
    
    if isinstance(permits, dict) and "error" in permits:
        return {"error": permits.get("message", "API error"), "permits": []}
    
    # Compute signals
    new_construction = [p for p in permits if "NEW CONSTRUCTION" in p.get("permit_type", "")]
    renovations = [p for p in permits if "RENOVATION" in p.get("permit_type", "")]
    
    total_cost = sum(float(p.get("reported_cost", 0)) for p in permits)
    
    # Major projects (>$500K)
    major = [
        {
            "description": p.get("work_description", "")[:200],
            "cost": float(p.get("reported_cost", 0)),
            "date": p.get("issue_date", "")[:10],
            "address": f"{p.get('street_number', '')} {p.get('street_direction', '')} {p.get('street_name', '')} {p.get('suffix', '')}".strip(),
            "sqft": p.get("_total_sqft"),
        }
        for p in permits
        if float(p.get("reported_cost", 0)) > 500000
    ]
    
    # Year-over-year trend
    now = datetime.now()
    last_12m = [p for p in permits if p.get("issue_date", "") > (now - timedelta(days=365)).strftime("%Y-%m-%d")]
    prior_12m = [p for p in permits if (now - timedelta(days=730)).strftime("%Y-%m-%d") < p.get("issue_date", "") <= (now - timedelta(days=365)).strftime("%Y-%m-%d")]
    
    return {
        "total_permits": len(permits),
        "new_construction_count": len(new_construction),
        "renovation_count": len(renovations),
        "total_reported_cost": total_cost,
        "major_projects": major[:5],  # Top 5 by cost
        "trend": {
            "last_12_months": len(last_12m),
            "prior_12_months": len(prior_12m),
            "direction": "increasing" if len(last_12m) > len(prior_12m) * 1.2 else "decreasing" if len(last_12m) < len(prior_12m) * 0.8 else "stable",
        },
        "radius_m": radius_m,
        "years": years,
        "min_cost_filter": min_cost,
    }
```

### Where it plugs in

**Option A (recommended): Add to the local agent**

The local agent already handles Chicago 311 data. Add building permits
as a second query in the same agent — it already knows how to handle
Socrata and how to degrade gracefully for non-Chicago cities:

```python
# In local_agent.py, after the 311 query:
from app.tools.building_permits import get_nearby_construction

construction_data = await get_nearby_construction(lat, lon)
# Merge into the local agent's output
result["nearby_construction"] = construction_data
```

**Option B: New "development agent"**

If you want it as a separate agent in the status bar (more visible to judges), create a new `development_agent.py` that wraps the tool + a Gemma 4 interpretation call.

### What the risk analyst sees

The risk analyst prompt now includes a new section:

```
## Nearby Development Activity (last 3 years, within 1km)
{
  "total_permits": 14,
  "new_construction_count": 8,
  "total_reported_cost": 12400000,
  "major_projects": [
    {
      "description": "NEW 5 STORY 24 UNIT RESIDENTIAL BUILDING",
      "cost": 3200000,
      "date": "2025-03-15",
      "address": "4600 S DREXEL BLVD",
      "sqft": "12000"
    },
    ...
  ],
  "trend": {
    "last_12_months": 9,
    "prior_12_months": 5,
    "direction": "increasing"
  }
}
```

### What the risk analyst says (with satellite + topo + street view + data)

> "From the satellite view, the block is currently ~75% impervious surface.
> The building permits data shows this is actively increasing: 8 new
> construction permits within 1km in the last 3 years, including a 24-unit
> residential building ($3.2M, 12,000 sq ft) 200m north.
>
> Year-over-year construction activity is increasing (9 permits in the last
> 12 months vs. 5 in the prior 12 months). This densification trend means
> the stormwater load on the combined sewer system is growing — even if the
> property's physical characteristics remain unchanged, the neighborhood's
> flood risk is rising.
>
> The topographic map confirms the property sits in a micro-depression.
> As impervious surface increases on the surrounding higher ground, more
> stormwater will funnel into this low point.
>
> This is a compounding risk: existing infrastructure vulnerability (combined
> sewers, below-grade entry points) + increasing environmental pressure
> (densification, impervious surface growth) + unchanged FEMA designation
> (Zone X, last updated [year])."

---

## Why this matters for the hackathon

### It's a genuinely novel insight

No existing flood risk tool connects building permits data to flood risk.
Not First Street, not FEMA, not any insurtech. This is a new signal.

### It's temporal

Most flood risk tools show a static snapshot. This shows a trajectory:
"your risk is increasing because of what's being built around you."
Judges love temporal analysis because it implies the tool gets more
valuable over time.

### It compounds with the other images

- **Satellite** shows current impervious surface
- **Building permits** show the trend — what it's becoming
- **Topo** shows where the water goes as surface increases
- **Street View** shows the property's vulnerability to that water

Four perspectives, one story. All connected by Gemma 4's reasoning.

### It's free and same-platform

Same Socrata SODA API as Chicago 311. Same query pattern. Same graceful
degradation for non-Chicago cities. Maybe 30 lines of new code.

---

## Non-Chicago cities (future work, note in writeup)

These cities also publish building permits on Socrata with geolocation:
- **NYC**: `data.cityofnewyork.us` (DOB NOW dataset)
- **Austin**: `data.austintexas.gov` (dataset `3syk-w9eu`)
- **LA**: `data.lacity.org` (dataset `pi9x-tg5x`)
- **SF**: `data.sfgov.org` (dataset `i98e-djp9`)

Same API pattern, same query structure. Adding more cities is just
configuring new dataset IDs — same tool code.

For the hackathon, Chicago alone is enough. In the writeup, mention that
the architecture supports any Socrata-based city portal.

---

## Dossier section: "Development pressure"

Add a new subsection to the FEMA gap section or as its own collapsible:

**§ Development pressure around your property**

> "In the last 3 years, 14 construction permits ($12.4M total) have been
> issued within 1km of your address, including 8 new construction projects.
> The largest is a 24-unit residential building at 4600 S Drexel Blvd
> ($3.2M, permitted March 2025).
>
> Construction activity is increasing: 9 permits in the last 12 months
> vs. 5 in the prior year. Each new project replaces absorbent ground
> with impervious surface, increasing stormwater runoff into the same
> combined sewer system that already overwhelms after 0.67 inches of
> rain per hour.
>
> Your flood risk isn't just about where you live — it's about what's
> being built around you."

---

## Action plan addition

Add to the advisor's action plan:

> "**Monitor nearby construction.** Large new developments near your
> property increase stormwater runoff into the shared sewer system.
> Check building permits at data.cityofchicago.org or sign up for
> permit alerts at chicagocityscape.com/permits. If a major project
> is permitted within your block, consider upgrading your backwater
> valve and sewer backup coverage."
