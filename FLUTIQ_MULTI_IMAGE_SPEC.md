# FlutIQ — Multi-Image Reasoning Spec

## The idea in one line

Feed the risk analyst 3 images + all agent data in one Gemma 4 call:
**street view (eye-level) + satellite (bird's-eye) + topographic (terrain contours)**.

---

## Why each image matters for flood risk

### Image 1: Street View (you already have this)

**What it reveals that data can't:**
- Lot elevation relative to street — is the house sitting *below* street grade?
- Basement-level window wells (the #1 water entry point in sewer backup flooding)
- Downspout connections — connected to ground (bad in combined sewer areas) or disconnected (good)
- Ground-floor HVAC, electrical panels, water heaters — what gets destroyed first
- Evidence of prior flooding — staining on foundation walls, patched concrete, replaced siding at base
- Visible sump pump discharge pipes on the exterior
- Presence or absence of backwater valve access caps in the yard

**How Gemma 4 should read it:**
- "I can see two window wells below street grade with no covers — primary flood entry risk"
- "Downspouts appear to discharge directly onto impervious surface adjacent to the foundation"
- "The lot sits approximately 8-12 inches below the road crown — surface runoff will flow toward the house"

**Token budget:** 1120 (max detail — need to see small features like pipes, wells, grates)


### Image 2: Satellite view (NEW — Mapbox `satellite-v9`)

**What it reveals that street view can't:**
- **Impervious surface percentage** — how much of the lot and surrounding block is concrete/asphalt vs. permeable ground. This is the single biggest predictor of urban flooding in combined sewer cities. More impervious surface = more runoff = more sewer load.
- **Green space vs. hardscape ratio** — a lot with a big backyard has infiltration capacity. A lot paved over has none.
- **Proximity to water bodies** — creeks, retention ponds, drainage channels within 500m that aren't visible from street level
- **Drainage patterns** — satellite shows the shape of the land: where water collects, where it flows, where it pools
- **Lot-to-building ratio** — a building that covers 90% of its lot has almost zero absorption capacity
- **Neighboring properties** — even if your lot has green space, if every neighbor is paved, runoff from their lots flows to yours
- **Flat rooftop area** — large flat roofs (common in Chicago) dump massive volumes into downspouts during storms

**How Gemma 4 should read it:**
- "From satellite, this block is approximately 75-80% impervious surface. The subject property has a small rear yard (~15% of lot) that provides minimal infiltration"
- "I can see a drainage channel approximately 200m to the southeast — but the terrain between the property and the channel appears flat, suggesting poor surface drainage"
- "Neighboring properties are similarly paved, creating a catchment effect where the entire block's runoff concentrates in the combined sewer"

**Token budget:** 560 (medium detail — need to distinguish pavement from vegetation, not read text)

**API call:**
```
GET https://api.mapbox.com/styles/v1/mapbox/satellite-v9/static/{lon},{lat},17,0/600x600@2x?access_token={MAPBOX_TOKEN}
```
Zoom 17 = tight neighborhood view. @2x for retina detail.


### Image 3: Topographic / outdoor map (NEW — Mapbox `outdoors-v12`)

**What it reveals that satellite can't:**
- **Contour lines** — the actual elevation shape of the terrain. Is the property in a depression? Does terrain slope toward or away from the house?
- **Terrain gradient direction** — in Chicago most of the city is flat, but micro-topography matters hugely. A 2-foot depression across a block creates a ponding zone.
- **Waterways and drainage infrastructure** — the outdoors-v12 style shows rivers, creeks, ditches, storm channels, and retention basins with labels
- **Relative elevation context** — is this property at the low point of a street? At the bottom of a grade? Near a known flood-prone intersection?
- **Distance to TARP access points** — the Deep Tunnel drop shafts are mapped; proximity means the local sewer connects to TARP, but also means potential capacity issues during peak events

**How Gemma 4 should read it:**
- "The topographic contour lines show this property sits in a subtle depression — the terrain rises approximately 1-2m to the north and west, meaning stormwater runoff from the surrounding 3-block area flows toward this location"
- "There is a mapped waterway 400m south — the contour lines indicate the property is above this waterway, so direct fluvial flooding is unlikely. The risk here is pluvial/sewer, not riverine — which is consistent with FEMA's Zone X designation being technically correct for riverine risk but missing the real threat"
- "No retention basin or detention pond visible within 500m — this neighborhood has no stormwater buffering beyond the sewer system"

**Token budget:** 280 (lower detail — contour lines are thick and readable, don't need pixel precision)

**API call:**
```
GET https://api.mapbox.com/styles/v1/mapbox/outdoors-v12/static/{lon},{lat},15,0/600x600@2x?access_token={MAPBOX_TOKEN}
```
Zoom 15 = wider area to show terrain context and drainage features.

---

## How these three images compound into insight

Each image alone gives partial information. Together they tell a story
that no single data source captures:

| Question | Street View | Satellite | Topo map | Data agents |
|----------|------------|-----------|----------|-------------|
| Is the lot below grade? | Yes (see it) | Partially | Yes (contours) | No |
| Impervious surface % | Partially (front only) | Yes (full lot + block) | No | NLCD has 30m resolution — too coarse |
| Drainage slope direction | No (eye-level) | Partially | Yes (contours) | No |
| Basement entry points | Yes (window wells) | No (overhead) | No | No |
| Proximity to waterways | No (can't see 200m away) | Partially | Yes (labeled) | USGS gauge but not spatial |
| Downspout connections | Yes | No | No | No |
| Building footprint ratio | No | Yes | No | No |
| Evidence of prior damage | Yes (staining, patches) | No | No | 311 data (indirect) |
| Micro-depression (ponding zone) | Partially | No | Yes | No |

**The risk analyst's reasoning trace should explicitly cross-reference:**
- "The satellite shows 80% impervious surface [image 2], the topo shows this block sits in a micro-depression [image 3], and the street view shows below-grade window wells [image 1]. Combined with 23 basement flooding 311 reports [data], this creates a compounding risk profile that FEMA's riverine model completely misses."

---

## Gemma 4 features exercised in this single call

- **Interleaved multimodal input** — 3 images + text in one prompt
- **Variable image resolution** — different token budgets per image (1120 for SV detail, 560 for satellite, 280 for topo)
- **Thinking/reasoning mode** — step-by-step cross-referencing visual + data evidence
- **Structured JSON output** — returns risk_score, visual_corroboration, key_risk_factors
- **Long context** — 3 images (~1860 visual tokens) + ~6-8K text tokens = well within 256K

---

## Implementation

### New file: `backend/app/tools/mapbox.py`

```python
import httpx
import os
import base64

MAPBOX_TOKEN = os.environ.get("MAPBOX_ACCESS_TOKEN", "")

async def get_satellite_image(lat: float, lon: float) -> str | None:
    """Fetch satellite image from Mapbox. Returns base64 or None."""
    if not MAPBOX_TOKEN:
        return None
    url = (
        f"https://api.mapbox.com/styles/v1/mapbox/satellite-v9"
        f"/static/{lon},{lat},17,0/600x600@2x"
        f"?access_token={MAPBOX_TOKEN}"
    )
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(url)
        if resp.status_code == 200:
            return base64.b64encode(resp.content).decode()
    return None

async def get_topo_image(lat: float, lon: float) -> str | None:
    """Fetch topographic/outdoor map from Mapbox. Returns base64 or None."""
    if not MAPBOX_TOKEN:
        return None
    url = (
        f"https://api.mapbox.com/styles/v1/mapbox/outdoors-v12"
        f"/static/{lon},{lat},15,0/600x600@2x"
        f"?access_token={MAPBOX_TOKEN}"
    )
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(url)
        if resp.status_code == 200:
            return base64.b64encode(resp.content).decode()
    return None
```

### Update orchestrator.py

Fetch both map images in parallel with existing data agents:

```python
# Add to the parallel fan-out alongside existing agents:
from app.tools.mapbox import get_satellite_image, get_topo_image

# Inside run_assessment, alongside existing agent_tasks:
satellite_task = asyncio.create_task(get_satellite_image(lat, lon))
topo_task = asyncio.create_task(get_topo_image(lat, lon))

# After agents complete:
satellite_b64 = await satellite_task  # may be None
topo_b64 = await topo_task            # may be None

# Pass all images to risk analyst:
risk_result = await run_risk_agent(
    results, lat, lon, display_name,
    streetview_image_b64=streetview_image_b64,
    satellite_image_b64=satellite_b64,
    topo_image_b64=topo_b64,
)
```

### Update risk_agent.py prompt

Build the content parts array with images first (Gemma 4 best practice):

```python
content_parts = []

# Images FIRST per Gemma 4 model card: "place image content before text"
if satellite_image_b64:
    content_parts.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{satellite_image_b64}"}})

if topo_image_b64:
    content_parts.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{topo_image_b64}"}})

if streetview_image_b64:
    content_parts.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{streetview_image_b64}"}})

# Then text
content_parts.append({"type": "text", "text": risk_prompt})
```

### Update risk analyst system prompt

Add these instructions:

```
You have up to three images of the property:

1. SATELLITE VIEW (bird's-eye): Look for impervious surface coverage
   (concrete/asphalt vs. green space), building footprint ratio,
   proximity to water bodies or drainage channels, and how the
   surrounding block is surfaced.

2. TOPOGRAPHIC MAP (contour lines): Look for elevation contours — is
   the property in a depression? Does terrain slope toward or away
   from the house? Are there mapped waterways, retention basins, or
   drainage infrastructure nearby?

3. STREET VIEW (eye-level): Look for lot elevation relative to street
   grade, basement-level windows, downspout connections, ground-floor
   utilities, and evidence of prior water damage.

Cross-reference what you see across all three views with the data from
our investigation agents. When visual evidence from one view
corroborates or contradicts another view or the data, say so explicitly.
```

### Update dossier JSON schema

Add a `visual_corroboration` field to the risk analyst output:

```json
{
  "risk_score": 72,
  "visual_corroboration": "Satellite confirms ~80% impervious surface on the block. Topo contours show a subtle depression centered on this lot. Street view shows below-grade window wells with no covers. All three views corroborate the 311 data showing concentrated basement flooding in this exact area.",
  ...
}
```

### Frontend: show the satellite + topo in the dossier

In the "What we saw at the property" section (§03), add the satellite
and topo images alongside the Street View photo. Three images in a row
or a tabbed view: "Street level | Satellite | Terrain."

---

## Environment variable

```
MAPBOX_ACCESS_TOKEN=pk.eyJ1...   # free account at mapbox.com
```

50K free static image loads/month. Each assessment uses 2 (satellite + topo).
That's 25K assessments/month on the free tier — more than enough.

---

## What this gives you for the hackathon

### For the video (the money shot)

Show the reasoning trace expanded. The model says:

"From the satellite view [image 1], I can see this block is approximately
80% impervious surface with the subject property covering most of its lot.
From the topographic map [image 2], the contour lines show a subtle
depression at this location — the terrain rises 1-2 meters to the north
and west. From the street view [image 3], the lot sits below street grade
with two uncovered window wells. All three visual perspectives converge on
the same conclusion: this property is at the low point of a heavily paved
catchment area with direct basement entry points, in a combined sewer
zone. The 23 basement flooding reports within 500m over 5 years are
entirely consistent with what I see."

That paragraph — where the model weaves together three different visual
perspectives with quantitative data — is something no other hackathon
submission will have.

### For the writeup (one paragraph to add)

"The risk analyst receives three images in a single Gemma 4 call: a
satellite view (impervious surface, drainage proximity, building
footprint), a topographic map (elevation contours, terrain slope,
waterway locations), and a street-level photograph (lot grade, entry
points, infrastructure condition). Using Gemma 4's interleaved
multimodal input and variable image resolution (1120 tokens for
street-level detail, 560 for satellite, 280 for terrain context), the
model cross-references what it sees across all three perspectives with
data from six public APIs — producing a reasoning trace that integrates
visual evidence with quantitative analysis in a single inference pass."

### For the capability checklist

```
[x] Multimodal vision — 3 images (street, satellite, topo)
[x] Interleaved multimodal input — images + text in one prompt
[x] Variable image resolution — different token budgets per image
[x] Reasoning mode — cross-referencing visual + data evidence
[x] Structured JSON output — risk score + visual corroboration
[x] Long context — 3 images + all agent data in one call
```

Six Gemma 4 capabilities composed in one inference call.
