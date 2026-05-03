"""GDELT 2.0 DOC API — recent flood news search. Free, no auth."""
import httpx

GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"


async def search_flood_news(
    city: str,
    state: str = "",
    max_results: int = 8,
    timespan: str = "6m",
) -> list[dict]:
    location = " ".join(p for p in (city, state) if p).strip()
    if not location:
        return []

    query = (
        f'("basement flooding" OR "sewer backup" OR "flood damage" '
        f'OR "flash flood") {location}'
    )
    params = {
        "query": query,
        "mode": "ArtList",
        "format": "json",
        "maxrecords": max_results,
        "timespan": timespan,
        "sort": "DateDesc",
    }

    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(GDELT_URL, params=params)
    if resp.status_code != 200:
        return []

    # GDELT sometimes returns HTML on bad queries; defensively parse.
    try:
        data = resp.json()
    except ValueError:
        return []

    articles = data.get("articles") or []
    return [
        {
            "title": a.get("title", ""),
            "source": a.get("domain", ""),
            "date": (a.get("seendate") or "")[:10],
            "url": a.get("url", ""),
        }
        for a in articles
    ]
