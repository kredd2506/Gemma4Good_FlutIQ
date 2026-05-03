"""GDELT 2.0 DOC API — recent flood news search. Free, no auth.

GDELT publicly enforces ~1 request per 5 seconds; over that and you
get HTTP 429 with a plain-text 'Please limit requests' body. The
news and archive agents both call this tool in parallel, so we
serialize calls process-wide via a lock and a minimum 5.5s gap.
This adds ~5s per assessment but eliminates silent empty results.
"""
import asyncio
import time

import httpx

GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
_MIN_GAP_SECONDS = 5.5
_lock = asyncio.Lock()
_last_call_at = 0.0


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

    global _last_call_at
    # GDELT limits to 1/5s per IP across ALL callers (other processes,
    # earlier curl tests, etc.). The intra-process lock can't see those,
    # so on 429 we wait the cool-down and retry once before giving up.
    async with _lock:
        for attempt in range(2):
            gap = time.monotonic() - _last_call_at
            if gap < _MIN_GAP_SECONDS:
                await asyncio.sleep(_MIN_GAP_SECONDS - gap)
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.get(GDELT_URL, params=params)
            _last_call_at = time.monotonic()
            if resp.status_code != 429:
                break
            if attempt == 0:
                await asyncio.sleep(_MIN_GAP_SECONDS + 1.0)

    if resp.status_code != 200:
        return []

    # GDELT returns HTML or plain text on rate-limit or bad queries.
    body = resp.text or ""
    if not body.strip().startswith(("{", "[")):
        return []
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
