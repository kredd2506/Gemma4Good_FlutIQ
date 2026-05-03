"""
Mapbox Static Images API — satellite + topographic map fetchers.

The risk analyst (v0.10+) reasons about three visual perspectives in
a single Gemma 4 inference call:

  - Street view (Google) — eye-level: lot grade, basement entries, downspouts
  - Satellite (Mapbox)   — bird's-eye: impervious surface %, drainage proximity
  - Topographic (Mapbox) — contour lines: micro-depressions, terrain slope

Each capture is fetched server-side, base64-encoded, and inlined as a
data: URL into the risk analyst's prompt. No upstream re-fetch.

Free tier: Mapbox gives 50K static-image loads/month per account, so
2 maps × 25K assessments/month is well within budget.

If MAPBOX_ACCESS_TOKEN is not set the helpers return None and the
risk analyst gracefully falls back to whatever images it does have
(Street View only, or none).
"""
import base64
from typing import Optional

import httpx

from app.config import MAPBOX_ACCESS_TOKEN

# Both endpoints follow the Static Images API contract:
#   /styles/v1/{user}/{style_id}/static/{lon},{lat},{zoom},{bearing}/{w}x{h}{@2x}
# We use the public 'mapbox' user's stock styles.
_BASE = "https://api.mapbox.com/styles/v1/mapbox"

# Satellite zoom 17 = tight neighborhood (~150m across @2x). Enough to
# distinguish individual buildings and impervious surfaces.
_SAT_STYLE = "satellite-v9"
_SAT_ZOOM = 17

# Topo / outdoor zoom 15 = wider area (~600m across @2x). Wide enough to
# show terrain context, drainage features, and named waterways.
_TOPO_STYLE = "outdoors-v12"
_TOPO_ZOOM = 15

# 600x600 @2x → 1200x1200 actual pixels. Good detail for vision tokens
# without blowing the context budget.
_SIZE = "600x600@2x"


def _is_configured() -> bool:
    return bool(MAPBOX_ACCESS_TOKEN)


async def _fetch_static(style: str, zoom: int, lat: float, lon: float) -> Optional[dict]:
    if not _is_configured():
        return None
    url = (
        f"{_BASE}/{style}/static/{lon},{lat},{zoom},0/{_SIZE}"
        f"?access_token={MAPBOX_ACCESS_TOKEN}"
    )
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(url)
    if resp.status_code != 200:
        return None
    ct = resp.headers.get("content-type", "image/png").split(";")[0].strip()
    b64 = base64.b64encode(resp.content).decode("ascii")
    return {
        "data_url": f"data:{ct};base64,{b64}",
        "bytes": len(resp.content),
        "style": style,
        "zoom": zoom,
        "lat": lat,
        "lon": lon,
    }


async def get_satellite_image(lat: float, lon: float) -> Optional[dict]:
    return await _fetch_static(_SAT_STYLE, _SAT_ZOOM, lat, lon)


async def get_topo_image(lat: float, lon: float) -> Optional[dict]:
    return await _fetch_static(_TOPO_STYLE, _TOPO_ZOOM, lat, lon)
