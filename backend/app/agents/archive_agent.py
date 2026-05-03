"""Historical flood-event archive agent.

NOAA Storm Events Database has no clean public JSON API (only CSV bulk
download per year), and ingesting that for a hackathon demo is
disproportionate. We use GDELT with a 2-year timespan as a proxy for
"established flooding track record" — same pipe as the news agent, but
asking Gemma 4 to characterize the historical pattern instead of the
recent event.
"""
import json

from app.llm.client import call_gemma4, extract_text, parse_json_response
from app.llm.prompts import ARCHIVE_AGENT_SYSTEM_PROMPT
from app.tools.gdelt import search_flood_news


async def run_archive_agent(
    county: str,
    state: str,
    lat: float,
    lon: float,
) -> dict:
    location = county or state
    articles = await search_flood_news(
        location, state, max_results=15, timespan="24m"
    )

    if not articles:
        return {
            "articles": [],
            "summary": f"No archived flood events found for {location}",
            "frequency_assessment": "unknown",
        }

    user_prompt = f"""Characterize the historical flood track record for {county}, {state} based on the following 24-month archive of flood-related news:

{json.dumps(articles, indent=2, default=str)}

Return a JSON object with:
- event_count: int (count of distinct events you can identify, not articles)
- frequency_assessment: "rare" | "occasional" | "frequent" | "chronic"
- dominant_flood_types: list of strings ("flash flood", "riverine", "urban / sewer backup", "coastal", "snowmelt")
- severity_trend: "decreasing" | "stable" | "increasing" | "unknown"
- representative_events: list of up to 3 {{date, description}} pulled from the articles
- summary: 1 sentence for the status feed

Return ONLY the JSON object, no other text."""

    response = await call_gemma4(
        messages=[
            {"role": "system", "content": ARCHIVE_AGENT_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.3,
    )

    text = extract_text(response)
    parsed = parse_json_response(text)
    if parsed:
        parsed["source"] = "GDELT 24-month news archive (Storm Events DB proxy)"
        return parsed

    return {
        "articles": articles[:5],
        "summary": f"Found {len(articles)} historical flood references",
        "interpretation_raw": text,
        "source": "GDELT 24-month news archive (Storm Events DB proxy)",
    }
