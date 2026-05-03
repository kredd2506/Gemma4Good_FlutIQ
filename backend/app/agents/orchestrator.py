"""
Runs all FloodIQ agents and yields SSE events to the client.

Flow:
  0. Geocode the address.
  1. Fan out 5 data-fetcher agents in parallel.
  2. Run risk-analyst agent (uses Gemma 4 reasoning over all data).
  3. Run advisor agent (needs the risk analysis).
  4. Emit complete{dossier}.

Each agent returns a dict with at least a "summary" key. If an agent
raises, the orchestrator emits an error event for that agent and
continues — partial dossiers beat crashes.
"""
import asyncio
import json
from typing import AsyncGenerator, Awaitable, Callable

from app.agents.advisor_agent import run_advisor_agent
from app.agents.archive_agent import run_archive_agent
from app.agents.fema_agent import run_fema_agent
from app.agents.local_agent import run_local_agent
from app.agents.news_agent import run_news_agent
from app.agents.risk_agent import run_risk_agent
from app.agents.weather_agent import run_weather_agent
from app.tools.geocoder import geocode_address


GeoCtx = dict
AgentFn = Callable[[GeoCtx], Awaitable[dict]]


async def _fema(ctx: GeoCtx) -> dict:
    return await run_fema_agent(ctx["lat"], ctx["lon"])


async def _local(ctx: GeoCtx) -> dict:
    return await run_local_agent(
        ctx["lat"], ctx["lon"], ctx.get("city", ""), ctx.get("state", "")
    )


async def _weather(ctx: GeoCtx) -> dict:
    return await run_weather_agent(ctx["lat"], ctx["lon"])


async def _news(ctx: GeoCtx) -> dict:
    return await run_news_agent(
        ctx.get("city", ""), ctx.get("state", ""), ctx["lat"], ctx["lon"]
    )


async def _archive(ctx: GeoCtx) -> dict:
    return await run_archive_agent(
        ctx.get("county", ""), ctx.get("state", ""), ctx["lat"], ctx["lon"]
    )


# Order here is the order the frontend renders agent rows in.
DATA_AGENTS: dict[str, AgentFn] = {
    "fema": _fema,
    "local": _local,
    "weather": _weather,
    "news": _news,
    "archive": _archive,
}


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


def _err_summary(e: Exception) -> str:
    msg = str(e) or type(e).__name__
    return f"Error: {msg[:140]}"


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
        "city": geo.get("city", ""),
        "state": geo.get("state", ""),
        "county": geo.get("county", ""),
    })

    # Announce all data agents up front so the UI can render rows.
    for name in DATA_AGENTS:
        yield sse("agent_update", {
            "agent": name,
            "status": "working",
            "summary": "Investigating...",
        })
    yield sse("agent_update", {
        "agent": "risk",
        "status": "queued",
        "summary": "Waiting on data agents...",
    })
    yield sse("agent_update", {
        "agent": "advisor",
        "status": "queued",
        "summary": "Waiting on risk analysis...",
    })

    # Run data agents in parallel; stream results in completion order.
    tasks = {name: asyncio.create_task(fn(ctx)) for name, fn in DATA_AGENTS.items()}
    task_to_name = {t: n for n, t in tasks.items()}
    pending = set(tasks.values())
    results: dict[str, dict] = {}

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
                results[name] = {"error": str(e), "summary": _err_summary(e)}
                yield sse("agent_update", {
                    "agent": name,
                    "status": "error",
                    "summary": _err_summary(e),
                })

    # Risk agent — uses Gemma 4 reasoning mode over all collected data.
    yield sse("agent_update", {
        "agent": "risk",
        "status": "working",
        "summary": "Synthesizing risk score with reasoning mode...",
    })
    try:
        risk_result = await run_risk_agent(
            results, geo["lat"], geo["lon"], geo["display_name"]
        )
        results["risk"] = risk_result
        yield sse("agent_update", {
            "agent": "risk",
            "status": "done",
            "summary": risk_result.get("summary", "Risk synthesis complete"),
        })
    except Exception as e:
        results["risk"] = {"error": str(e), "summary": _err_summary(e)}
        yield sse("agent_update", {
            "agent": "risk",
            "status": "error",
            "summary": _err_summary(e),
        })

    # Advisor agent — translates risk into actions.
    yield sse("agent_update", {
        "agent": "advisor",
        "status": "working",
        "summary": "Generating insurance + mitigation plan...",
    })
    try:
        advisor_result = await run_advisor_agent(results, geo["display_name"])
        results["advisor"] = advisor_result
        yield sse("agent_update", {
            "agent": "advisor",
            "status": "done",
            "summary": advisor_result.get("summary", "Recommendations ready"),
        })
    except Exception as e:
        results["advisor"] = {"error": str(e), "summary": _err_summary(e)}
        yield sse("agent_update", {
            "agent": "advisor",
            "status": "error",
            "summary": _err_summary(e),
        })

    yield sse("complete", {"dossier": _compile_dossier(geo, results)})


def _compile_dossier(geo: GeoCtx, results: dict) -> dict:
    return {
        "address": geo["display_name"],
        "coordinates": {"lat": geo["lat"], "lon": geo["lon"]},
        "city": geo.get("city", ""),
        "state": geo.get("state", ""),
        "county": geo.get("county", ""),
        "fema": results.get("fema", {}),
        "local": results.get("local", {}),
        "weather": results.get("weather", {}),
        "news": results.get("news", {}),
        "archive": results.get("archive", {}),
        "risk": results.get("risk", {}),
        "advisor": results.get("advisor", {}),
    }
