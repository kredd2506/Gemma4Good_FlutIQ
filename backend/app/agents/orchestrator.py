"""
Runs all FloodIQ agents and yields SSE events to the client.

Flow:
  0. Geocode the address.
  1. Run data-fetcher agents concurrently.
  2. Run risk-analyst agent (needs all data, uses Gemma 4 reasoning).
  3. Run advisor agent (needs the risk analysis).
  4. Yield the compiled dossier.

Agents register themselves in DATA_AGENTS so this file does not have
to know about every agent's signature.
"""
import asyncio
import json
from typing import AsyncGenerator, Awaitable, Callable

from app.agents.fema_agent import run_fema_agent
from app.tools.geocoder import geocode_address


GeoCtx = dict
AgentFn = Callable[[GeoCtx], Awaitable[dict]]


async def _fema(ctx: GeoCtx) -> dict:
    return await run_fema_agent(ctx["lat"], ctx["lon"])


# As we implement more agents, add them here. Frontend uses these keys
# to know which agent rows to render.
DATA_AGENTS: dict[str, AgentFn] = {
    "fema": _fema,
}


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


async def run_assessment(address: str) -> AsyncGenerator[str, None]:
    geo = await geocode_address(address)
    if not geo:
        yield sse("error", {"message": f"Could not geocode address: {address!r}"})
        return

    ctx: GeoCtx = geo
    yield sse("geocoded", {
        "address": geo["display_name"],
        "lat": geo["lat"],
        "lon": geo["lon"],
    })

    # Announce all agents as working up front so the UI can render rows.
    for name in DATA_AGENTS:
        yield sse("agent_update", {
            "agent": name,
            "status": "working",
            "summary": "Investigating...",
        })

    # Kick off all data agents in parallel.
    tasks = {name: asyncio.create_task(fn(ctx)) for name, fn in DATA_AGENTS.items()}

    results: dict[str, dict] = {}
    # Stream completions as they finish, not in launch order.
    pending = set(tasks.values())
    task_to_name = {t: n for n, t in tasks.items()}

    while pending:
        done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
        for t in done:
            name = task_to_name[t]
            try:
                result = t.result()
                results[name] = result
                yield sse("agent_update", {
                    "agent": name,
                    "status": "done",
                    "summary": result.get("summary", "Complete"),
                })
            except Exception as e:
                results[name] = {"error": str(e), "summary": f"Error: {str(e)[:120]}"}
                yield sse("agent_update", {
                    "agent": name,
                    "status": "error",
                    "summary": f"Error: {str(e)[:120]}",
                })

    # Risk and advisor will be added next vertical slice.
    dossier = _compile_dossier(geo, results)
    yield sse("complete", {"dossier": dossier})


def _compile_dossier(geo: GeoCtx, results: dict) -> dict:
    return {
        "address": geo["display_name"],
        "coordinates": {"lat": geo["lat"], "lon": geo["lon"]},
        **{name: results.get(name, {}) for name in DATA_AGENTS},
    }
