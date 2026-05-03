"""FEMA NFHL flood zone lookup via ArcGIS REST. Free, no API key."""
import httpx

FEMA_URL = (
    "https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28/query"
)


async def lookup_fema_flood_zone(latitude: float, longitude: float) -> dict:
    # The spec previously listed VERSION_ID here — that field does not
    # exist on layer 28 and causes ArcGIS to return HTTP 200 with an
    # {"error": ...} body, which silently looked like UNMAPPED.
    out_fields = ",".join([
        "FLD_ZONE",
        "ZONE_SUBTY",
        "SFHA_TF",       # "T" / "F" — official SFHA flag
        "STATIC_BFE",
        "DEPTH",
        "STUDY_TYP",
        "DFIRM_ID",
        "SOURCE_CIT",
    ])
    params = {
        "geometry": (
            f'{{"x":{longitude},"y":{latitude},'
            f'"spatialReference":{{"wkid":4326}}}}'
        ),
        "geometryType": "esriGeometryPoint",
        "inSR": "4326",
        "outFields": out_fields,
        "returnGeometry": "false",
        "f": "json",
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(FEMA_URL, params=params)
    resp.raise_for_status()
    data = resp.json()

    # ArcGIS returns 200 + {"error": {...}} on bad queries.
    if isinstance(data, dict) and "error" in data:
        return {
            "FLD_ZONE": "ERROR",
            "error": data["error"],
        }

    features = data.get("features") or []
    if not features:
        return {
            "FLD_ZONE": "UNMAPPED",
            "note": "No FEMA NFHL polygon at this point",
        }

    return features[0].get("attributes") or {}
