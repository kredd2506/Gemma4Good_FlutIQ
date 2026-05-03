"""
Google Street View Static API tool.

Strategy (per Google's guidance):
  1. Hit /streetview/metadata first — FREE, doesn't count against
     billing quota. Tells us if there's actual panorama coverage.
  2. If status == OK at the requested point or within a small radius,
     fetch the actual image at the panorama's true lat/lon (which may
     differ from the input by tens of meters if Google snapped to the
     nearest street).
  3. If no coverage anywhere within 500m, return None — the agent
     surfaces an honest "no street-level imagery" finding instead
     of feeding the gray "no imagery" placeholder to the vision
     model (which would hallucinate features in gray pixels).

The image is returned as a data: URL (base64-encoded) so we can
inline it directly into the Gemma 4 vision request without making
the upstream provider re-fetch (which we learned the hard way fails
when User-Agent rules block the upstream).
"""
import base64
import math
from typing import Optional

import httpx

from app.config import GOOGLE_MAPS_API_KEY

METADATA_URL = "https://maps.googleapis.com/maps/api/streetview/metadata"
IMAGE_URL = "https://maps.googleapis.com/maps/api/streetview"

# Try increasingly wider radii until we find a panorama.
# Most addresses with coverage hit on the first attempt; the 500m
# fallback catches addresses on private roads or driveways where the
# nearest pano is a block or two away.
SEARCH_RADII_M = (None, 50, 200, 500)

# Bias the camera angle slightly downward — flood-risk indicators
# (basement windows, ground-floor HVAC, drainage) are at street level
# and below.
DEFAULT_PITCH = -5
DEFAULT_FOV = 90


def _bearing_deg(from_lat: float, from_lon: float, to_lat: float, to_lon: float) -> float:
    """Compute the initial bearing (in degrees, 0=N, 90=E) from one
    coordinate to another. Used to aim the Street View camera from the
    captured panorama back toward the user's geocoded address."""
    phi1 = math.radians(from_lat)
    phi2 = math.radians(to_lat)
    dlon = math.radians(to_lon - from_lon)
    x = math.sin(dlon) * math.cos(phi2)
    y = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlon)
    return (math.degrees(math.atan2(x, y)) + 360.0) % 360.0


async def _metadata(client: httpx.AsyncClient, lat: float, lon: float, radius: Optional[int]) -> dict:
    params = {
        "location": f"{lat},{lon}",
        "key": GOOGLE_MAPS_API_KEY,
    }
    if radius is not None:
        params["radius"] = str(radius)
    resp = await client.get(METADATA_URL, params=params)
    if resp.status_code != 200:
        return {"status": f"HTTP_{resp.status_code}"}
    return resp.json() or {}


async def fetch_streetview_for(lat: float, lon: float, size: str = "640x480") -> dict:
    """
    Fetch the best available Street View image near (lat, lon).

    Returns:
        On success:
          {
            "available": True,
            "image_data_url": "data:image/jpeg;base64,...",
            "pano_id": str,
            "pano_lat": float, "pano_lon": float,
            "capture_date": "YYYY-MM",
            "radius_m": int (which radius found it; None = exact),
          }
        On no coverage:
          {"available": False, "reason": "no panorama within 500m"}
        On config error:
          {"available": False, "reason": "GOOGLE_MAPS_API_KEY not set"}
    """
    if not GOOGLE_MAPS_API_KEY:
        return {"available": False, "reason": "GOOGLE_MAPS_API_KEY not set"}

    async with httpx.AsyncClient(timeout=20) as client:
        meta = None
        used_radius = None
        for radius in SEARCH_RADII_M:
            meta = await _metadata(client, lat, lon, radius)
            if meta.get("status") == "OK":
                used_radius = radius
                break

        if not meta or meta.get("status") != "OK":
            return {
                "available": False,
                "reason": f"no Street View panorama within {SEARCH_RADII_M[-1]}m",
                "metadata_status": meta.get("status") if meta else "unknown",
            }

        pano_loc = meta.get("location") or {}
        pano_lat = pano_loc.get("lat", lat)
        pano_lon = pano_loc.get("lng", lon)

        # Aim the camera back at the user's actual address. Without
        # this, the API picks a default heading that often shows the
        # road instead of the building.
        heading = _bearing_deg(pano_lat, pano_lon, lat, lon)

        img_params = {
            "size": size,
            "location": f"{pano_lat},{pano_lon}",
            "heading": f"{heading:.1f}",
            "fov": str(DEFAULT_FOV),
            "pitch": str(DEFAULT_PITCH),
            "key": GOOGLE_MAPS_API_KEY,
            "return_error_code": "true",  # 4xx instead of placeholder image
        }
        img_resp = await client.get(IMAGE_URL, params=img_params)
        if img_resp.status_code != 200:
            return {
                "available": False,
                "reason": f"image fetch returned HTTP {img_resp.status_code}",
            }

        b64 = base64.b64encode(img_resp.content).decode("ascii")
        ct = img_resp.headers.get("content-type", "image/jpeg").split(";")[0].strip()

        return {
            "available": True,
            "image_data_url": f"data:{ct};base64,{b64}",
            "image_bytes": len(img_resp.content),
            "pano_id": meta.get("pano_id"),
            "pano_lat": pano_lat,
            "pano_lon": pano_lon,
            "heading_deg": heading,
            "capture_date": meta.get("date"),
            "copyright": meta.get("copyright"),
            "radius_m": used_radius,
        }
