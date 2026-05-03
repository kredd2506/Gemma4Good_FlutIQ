"""Recent flood news agent (GDELT 6-month window)."""
import json

from app.llm.client import call_gemma4, extract_text, parse_json_response
from app.llm.prompts import NEWS_AGENT_SYSTEM_PROMPT
from app.tools.gdelt import search_flood_news


async def run_news_agent(city: str, state: str, lat: float, lon: float) -> dict:
    articles = await search_flood_news(city, state, max_results=8, timespan="6m")

    if not articles:
        return {
            "articles": [],
            "key_themes": [],
            "summary": f"No recent flood news found for {city or 'this area'}",
        }

    user_prompt = f"""Summarize these recent flood-related news articles for {city}, {state}:

{json.dumps(articles, indent=2, default=str)}

Return a JSON object with:
- articles: pass through the input list (title, source, date, url) unchanged
- key_themes: 2-4 short bullet themes (e.g., "Recurring sewer backups in basements")
- recent_event_summary: 1-2 sentences on the most significant recent event, or null if nothing stands out
- summary: 1 sentence for the status feed

Return ONLY the JSON object, no other text."""

    response = await call_gemma4(
        messages=[
            {"role": "system", "content": NEWS_AGENT_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.3,
    )

    text = extract_text(response)
    parsed = parse_json_response(text)
    if parsed:
        # Always trust the original article list (Gemma sometimes truncates).
        parsed["articles"] = articles
        return parsed

    return {
        "articles": articles,
        "summary": f"Found {len(articles)} recent flood-related articles",
        "interpretation_raw": text,
    }
