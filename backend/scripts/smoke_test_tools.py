"""Smoke-test just function calling on Gemma 4 (after rate-limit clears)."""
import asyncio
import json
import os
import sys

import httpx

API_KEY = os.environ["OPENROUTER_API_KEY"]
BASE = "https://openrouter.ai/api/v1/chat/completions"
HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
    "HTTP-Referer": "https://floodiq.pages.dev",
    "X-Title": "FloodIQ smoke test",
}

TOOLS = [{
    "type": "function",
    "function": {
        "name": "lookup_fema_flood_zone",
        "description": "Look up FEMA flood zone for coordinates.",
        "parameters": {
            "type": "object",
            "properties": {
                "latitude": {"type": "number"},
                "longitude": {"type": "number"},
            },
            "required": ["latitude", "longitude"],
        },
    },
}]


async def try_model(model: str) -> bool:
    print(f"\n--- {model} ---")
    payload = {
        "model": model,
        "messages": [{
            "role": "user",
            "content": "What is the FEMA flood zone for 41.8087, -87.6062? Use the tool.",
        }],
        "tools": TOOLS,
        "tool_choice": "auto",
        "max_tokens": 512,
        "temperature": 0,
    }
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(BASE, headers=HEADERS, json=payload)
    print(f"HTTP {resp.status_code}")
    if resp.status_code != 200:
        print(resp.text[:500])
        return False
    msg = resp.json()["choices"][0]["message"]
    text = msg.get("content", "") or ""
    tool_calls = msg.get("tool_calls", []) or []
    print(f"content: {text[:200]!r}")
    print(f"tool_calls ({len(tool_calls)}):")
    for tc in tool_calls:
        print(f"  {json.dumps(tc)[:300]}")
    return bool(tool_calls)


async def main() -> int:
    for model in ("google/gemma-4-31b-it:free", "google/gemma-4-26b-a4b-it:free"):
        ok = await try_model(model)
        if ok:
            print("\nPASS")
            return 0
    print("\nFAIL on both models")
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
