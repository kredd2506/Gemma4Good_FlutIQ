"""
Smoke test: confirm Gemma 4 free tier on OpenRouter supports
the two features FloodIQ depends on:
  1. reasoning mode (risk-analyst agent)
  2. OpenAI-format tool calling (data agents)

Run:
    cd backend && set -a && source .env && set +a && .venv/bin/python scripts/smoke_test.py
"""
import asyncio
import json
import os
import sys

import httpx

API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
BASE = "https://openrouter.ai/api/v1/chat/completions"
PRIMARY = "google/gemma-4-31b-it:free"
FALLBACK = "google/gemma-4-26b-a4b-it:free"

HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
    "HTTP-Referer": "https://floodiq.pages.dev",
    "X-Title": "FloodIQ smoke test",
}


def section(title: str) -> None:
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


async def call(payload: dict) -> dict:
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(BASE, headers=HEADERS, json=payload)
    print(f"  HTTP {resp.status_code}")
    if resp.status_code != 200:
        print(f"  body: {resp.text[:600]}")
        return {}
    return resp.json()


async def test_basic(model: str) -> bool:
    section(f"TEST 1 — basic completion ({model})")
    data = await call({
        "model": model,
        "messages": [{"role": "user", "content": "Say only: pong"}],
        "max_tokens": 16,
        "temperature": 0,
    })
    if not data:
        return False
    text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    print(f"  response: {text!r}")
    return bool(text)


async def test_reasoning(model: str) -> bool:
    section(f"TEST 2 — reasoning mode ({model})")
    data = await call({
        "model": model,
        "messages": [{
            "role": "user",
            "content": (
                "If the annual exceedance probability of a flood is 0.01, "
                "what is the probability of at least one flood in 30 years? "
                "Show your work, then return only the final number."
            ),
        }],
        "reasoning": {"enabled": True},
        "max_tokens": 1024,
        "temperature": 0,
    })
    if not data:
        return False
    msg = data.get("choices", [{}])[0].get("message", {})
    text = msg.get("content", "")
    reasoning_details = msg.get("reasoning_details", [])
    reasoning_field = msg.get("reasoning", "")
    print(f"  content (first 300 chars): {text[:300]!r}")
    print(f"  reasoning_details present: {bool(reasoning_details)} (len={len(reasoning_details)})")
    print(f"  reasoning field present: {bool(reasoning_field)} (len={len(reasoning_field) if isinstance(reasoning_field, str) else 'n/a'})")
    if reasoning_details:
        first = reasoning_details[0]
        print(f"  reasoning_details[0] keys: {list(first.keys()) if isinstance(first, dict) else type(first).__name__}")
        sample = json.dumps(first)[:300] if isinstance(first, dict) else str(first)[:300]
        print(f"  reasoning_details[0] sample: {sample}")
    elif reasoning_field:
        sample = reasoning_field[:300] if isinstance(reasoning_field, str) else str(reasoning_field)[:300]
        print(f"  reasoning sample: {sample!r}")
    print(f"  usage: {data.get('usage', {})}")
    return bool(reasoning_details or reasoning_field)


async def test_tools(model: str) -> bool:
    section(f"TEST 3 — function calling ({model})")
    tools = [{
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
    data = await call({
        "model": model,
        "messages": [{
            "role": "user",
            "content": "What is the FEMA flood zone for 41.8087, -87.6062?",
        }],
        "tools": tools,
        "tool_choice": "auto",
        "max_tokens": 512,
        "temperature": 0,
    })
    if not data:
        return False
    msg = data.get("choices", [{}])[0].get("message", {})
    tool_calls = msg.get("tool_calls", []) or []
    text = msg.get("content", "") or ""
    print(f"  content: {text[:200]!r}")
    print(f"  tool_calls count: {len(tool_calls)}")
    if tool_calls:
        tc = tool_calls[0]
        print(f"  tool_call[0]: {json.dumps(tc)[:400]}")
    return bool(tool_calls)


async def main() -> int:
    if not API_KEY:
        print("ERROR: OPENROUTER_API_KEY not set", file=sys.stderr)
        return 2

    results = {}
    for model in (PRIMARY, FALLBACK):
        results[(model, "basic")] = await test_basic(model)
        results[(model, "reasoning")] = await test_reasoning(model)
        results[(model, "tools")] = await test_tools(model)

    section("SUMMARY")
    for (model, name), ok in results.items():
        mark = "PASS" if ok else "FAIL"
        print(f"  [{mark}] {model:42s} {name}")

    all_critical = all([
        results.get((PRIMARY, "basic"), False),
        results.get((PRIMARY, "reasoning"), False) or results.get((FALLBACK, "reasoning"), False),
        results.get((PRIMARY, "tools"), False) or results.get((FALLBACK, "tools"), False),
    ])
    print()
    print("Overall:", "OK to proceed" if all_critical else "BLOCKED — adjust spec before building")
    return 0 if all_critical else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
