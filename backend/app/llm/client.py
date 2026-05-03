"""
Gemma 4 client via OpenRouter free tier.

Uses the OpenAI-compatible chat/completions endpoint. Supports function
calling and reasoning mode (the latter is the risk-analyst agent's
showcase capability).

Notes from the smoke test (scripts/smoke_test.py):
- Reasoning trace lives at message.reasoning_details[i].text — the
  earlier spec said .content, which is wrong on Gemma 4 / OpenRouter
  today. We also fall back to the top-level message.reasoning string
  that OpenRouter returns concatenated for convenience.
- The shared :free upstream pool 429s very quickly (we got rate-limited
  after 2 calls). BYOK a Google AI Studio key into OpenRouter
  integrations for the demo. We retry on 429 with the fallback model,
  then exponential backoff up to a cap.
"""
import asyncio
import json
from typing import Optional

import httpx

from app.config import (
    APP_URL,
    APP_NAME,
    MODEL_FALLBACK,
    MODEL_PRIMARY,
    OPENROUTER_API_KEY,
    OPENROUTER_BASE,
)


class RateLimitedError(Exception):
    """All retries exhausted while upstream was rate-limiting."""


async def call_gemma4(
    messages: list[dict],
    tools: Optional[list[dict]] = None,
    model: str = MODEL_PRIMARY,
    reasoning: bool = False,
    max_tokens: int = 4096,
    temperature: float = 0.3,
    retries: int = 3,
) -> dict:
    """
    Call Gemma 4 via OpenRouter. Returns the raw response JSON.

    Retry policy:
      - On 429 with primary model: switch to fallback model, then retry
        with exponential backoff (2s, 4s, 8s).
      - On timeout: short retry.
    """
    if not OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY is not set")

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": APP_URL,
        "X-Title": APP_NAME,
    }

    payload: dict = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    if reasoning:
        payload["reasoning"] = {"enabled": True}

    current_model = model
    backoff = 2.0

    async with httpx.AsyncClient(timeout=120) as client:
        for attempt in range(retries + 1):
            try:
                resp = await client.post(
                    f"{OPENROUTER_BASE}/chat/completions",
                    headers=headers,
                    json={**payload, "model": current_model},
                )
            except httpx.TimeoutException:
                if attempt >= retries:
                    raise
                await asyncio.sleep(backoff)
                backoff *= 2
                continue

            if resp.status_code == 429:
                if current_model == MODEL_PRIMARY and attempt == 0:
                    current_model = MODEL_FALLBACK
                    continue
                if attempt >= retries:
                    raise RateLimitedError(
                        f"Both Gemma 4 free models rate-limited after {retries + 1} attempts. "
                        "BYOK a Google AI Studio key at openrouter.ai/settings/integrations."
                    )
                await asyncio.sleep(backoff)
                backoff *= 2
                continue

            # Transient upstream errors (502/503/504 are common when an
            # OpenRouter provider hiccups). Retry with backoff before
            # surfacing to the user as an agent error.
            if resp.status_code in (500, 502, 503, 504):
                if attempt >= retries:
                    resp.raise_for_status()
                await asyncio.sleep(backoff)
                backoff *= 2
                continue

            resp.raise_for_status()
            return resp.json()

    raise RuntimeError("call_gemma4 exited retry loop without returning")


def extract_text(response: dict) -> str:
    choices = response.get("choices") or []
    if not choices:
        return ""
    return (choices[0].get("message") or {}).get("content") or ""


def extract_tool_calls(response: dict) -> list[dict]:
    choices = response.get("choices") or []
    if not choices:
        return []
    return (choices[0].get("message") or {}).get("tool_calls") or []


def extract_reasoning(response: dict) -> str:
    """
    Extract the chain-of-thought reasoning trace from a Gemma 4 response.

    OpenRouter returns reasoning two ways for Gemma 4:
      1. message.reasoning_details: [{type, text, format, index}, ...]
      2. message.reasoning: "<concatenated string>"

    The (1) form is canonical (per-block, indexable). The (2) form is a
    convenience concatenation. We prefer (1) and fall back to (2).
    """
    choices = response.get("choices") or []
    if not choices:
        return ""
    msg = choices[0].get("message") or {}

    details = msg.get("reasoning_details") or []
    if details:
        parts = []
        for d in details:
            if not isinstance(d, dict):
                continue
            text = d.get("text") or d.get("content") or ""
            if text:
                parts.append(text)
        if parts:
            return "\n".join(parts)

    reasoning = msg.get("reasoning")
    if isinstance(reasoning, str) and reasoning:
        return reasoning
    return ""


def parse_json_response(text: str) -> Optional[dict]:
    """Strip ```json fences and parse. Return None on failure."""
    if not text:
        return None
    clean = text.strip()
    if clean.startswith("```"):
        clean = clean.split("\n", 1)[1] if "\n" in clean else clean[3:]
        if clean.endswith("```"):
            clean = clean.rsplit("```", 1)[0]
        clean = clean.strip()
    if clean.startswith("json"):
        clean = clean[4:].strip()
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        return None


async def run_tool_loop(
    system_prompt: str,
    user_prompt: str,
    tools: list[dict],
    tool_handlers: dict,
    max_iterations: int = 5,
    model: str = MODEL_PRIMARY,
) -> str:
    """
    Run a Gemma 4 agent that can call tools.

    tool_handlers: dict mapping function name → async callable that
    returns a JSON-serializable result.
    """
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    for _ in range(max_iterations):
        response = await call_gemma4(messages, tools=tools, model=model)
        tool_calls = extract_tool_calls(response)

        if not tool_calls:
            return extract_text(response)

        messages.append(response["choices"][0]["message"])

        for tc in tool_calls:
            fn_name = tc["function"]["name"]
            try:
                fn_args = json.loads(tc["function"]["arguments"])
            except json.JSONDecodeError:
                fn_args = {}

            handler = tool_handlers.get(fn_name)
            if handler:
                try:
                    result = await handler(**fn_args)
                except Exception as e:
                    result = {"error": str(e)}
            else:
                result = {"error": f"Unknown tool: {fn_name}"}

            messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": json.dumps(result, default=str),
            })

    return extract_text(response)
