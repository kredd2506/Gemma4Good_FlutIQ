# FloodIQ Backend — Build Instructions for Claude Code

> **Context**: The React frontend prototype is done. This document tells you how to build the Python/FastAPI backend that powers it. The frontend expects an SSE endpoint at `POST /api/assess` that streams agent status updates and a final dossier JSON.

---

## 1. What you're building

A FastAPI backend with 7 specialized agents, each powered by Gemma 4 via OpenRouter's free API. The agents run concurrently, fetch data from free public APIs, and stream progress to the frontend via Server-Sent Events.

**This is a Kaggle hackathon submission for the Gemma 4 Good Hackathon.** The judges will evaluate:
- How effectively Gemma 4 is used (function calling, reasoning, agentic workflows)
- Real-world impact
- Working demo

**Critical hackathon requirement**: Gemma 4 must be the LLM. Use it via OpenRouter free tier. The model IDs are:
- `google/gemma-4-31b-it:free` (primary — 256K context, native function calling, reasoning)
- `google/gemma-4-26b-a4b-it:free` (fallback — MoE, same features, faster)

---

## 2. Project structure

```
backend/
├── app/
│   ├── __init__.py
│   ├── main.py                    # FastAPI app, CORS, lifespan
│   ├── config.py                  # Environment variables, constants
│   ├── api/
│   │   ├── __init__.py
│   │   ├── health.py              # GET /api/health
│   │   └── assess.py              # POST /api/assess (SSE endpoint)
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── orchestrator.py        # Runs all agents, streams updates
│   │   ├── fema_agent.py          # FEMA flood zone lookup
│   │   ├── local_agent.py         # Chicago 311 + sewer data
│   │   ├── weather_agent.py       # USGS + NOAA + Open-Meteo
│   │   ├── news_agent.py          # GDELT recent flood news
│   │   ├── archive_agent.py       # NOAA Storm Events history
│   │   ├── risk_agent.py          # Risk score computation (Gemma 4 reasoning)
│   │   └── advisor_agent.py       # Insurance recs + action plan
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── fema.py                # FEMA NFHL ArcGIS REST client
│   │   ├── chicago_311.py         # Socrata SODA API client
│   │   ├── usgs.py                # USGS Water Services client
│   │   ├── noaa.py                # NOAA NWS API client
│   │   ├── open_meteo.py          # Open-Meteo flood API client
│   │   ├── gdelt.py               # GDELT news search client
│   │   ├── geocoder.py            # Nominatim geocoding
│   │   └── elevation.py           # USGS 3DEP elevation API
│   ├── llm/
│   │   ├── __init__.py
│   │   ├── client.py              # OpenRouter API client wrapper
│   │   └── prompts.py             # System prompts for each agent
│   └── models/
│       ├── __init__.py
│       └── schemas.py             # Pydantic models
├── Dockerfile
├── requirements.txt
└── README.md                      # HF Spaces frontmatter
```

---

## 3. Core implementation details

### 3.1 The LLM client (`app/llm/client.py`)

This is the most critical file. It wraps OpenRouter's API with Gemma 4 function calling.

```python
"""
Gemma 4 client via OpenRouter free tier.
Uses OpenAI-compatible chat/completions endpoint.
Supports function calling and reasoning mode.
"""
import httpx
import os
import json
import asyncio
from typing import Optional

OPENROUTER_BASE = "https://openrouter.ai/api/v1"
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")

# Free models — $0/M tokens
MODEL_PRIMARY = "google/gemma-4-31b-it:free"
MODEL_FALLBACK = "google/gemma-4-26b-a4b-it:free"

async def call_gemma4(
    messages: list[dict],
    tools: Optional[list[dict]] = None,
    model: str = MODEL_PRIMARY,
    reasoning: bool = False,
    max_tokens: int = 4096,
    temperature: float = 0.3,
    retries: int = 2,
) -> dict:
    """
    Call Gemma 4 via OpenRouter.
    
    Args:
        messages: OpenAI-format messages list
        tools: Optional list of tool/function definitions (OpenAI format)
        model: Model ID string
        reasoning: If True, enables Gemma 4's thinking mode
        max_tokens: Max output tokens
        temperature: Sampling temperature
        retries: Number of retry attempts on rate limit
    
    Returns:
        OpenAI-compatible response dict
    """
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://floodiq.pages.dev",
        "X-Title": "FloodIQ",
    }
    
    payload = {
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
    
    for attempt in range(retries + 1):
        try:
            async with httpx.AsyncClient(timeout=90) as client:
                resp = await client.post(
                    f"{OPENROUTER_BASE}/chat/completions",
                    headers=headers,
                    json=payload,
                )
                
                if resp.status_code == 429:
                    # Rate limited — try fallback model or wait
                    if model == MODEL_PRIMARY and attempt == 0:
                        return await call_gemma4(
                            messages, tools, MODEL_FALLBACK,
                            reasoning, max_tokens, temperature, retries=1
                        )
                    wait = 2 ** attempt
                    await asyncio.sleep(wait)
                    continue
                
                resp.raise_for_status()
                return resp.json()
                
        except httpx.TimeoutException:
            if attempt < retries:
                await asyncio.sleep(2)
                continue
            raise
    
    raise Exception("Gemma 4 API call failed after retries")


def extract_text(response: dict) -> str:
    """Extract text content from OpenRouter response."""
    choices = response.get("choices", [])
    if not choices:
        return ""
    message = choices[0].get("message", {})
    return message.get("content", "") or ""


def extract_tool_calls(response: dict) -> list[dict]:
    """Extract tool calls from OpenRouter response."""
    choices = response.get("choices", [])
    if not choices:
        return []
    message = choices[0].get("message", {})
    return message.get("tool_calls", [])


def extract_reasoning(response: dict) -> str:
    """Extract reasoning/thinking from OpenRouter response."""
    choices = response.get("choices", [])
    if not choices:
        return ""
    message = choices[0].get("message", {})
    reasoning = message.get("reasoning_details", [])
    if reasoning:
        return "\n".join(r.get("content", "") for r in reasoning)
    return ""
```

### 3.2 How Gemma 4 function calling works with OpenRouter

OpenRouter uses the OpenAI-compatible format. Define tools like this:

```python
# Example: defining a tool for the FEMA agent
FEMA_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "lookup_fema_flood_zone",
            "description": "Look up the FEMA flood zone designation for a geographic coordinate. Returns the flood zone code, base flood elevation, and whether it is a Special Flood Hazard Area.",
            "parameters": {
                "type": "object",
                "properties": {
                    "latitude": {
                        "type": "number",
                        "description": "Latitude of the location"
                    },
                    "longitude": {
                        "type": "number",
                        "description": "Longitude of the location"
                    }
                },
                "required": ["latitude", "longitude"]
            }
        }
    }
]
```

The agentic loop:

```python
async def run_agent_with_tools(system_prompt, user_prompt, tools, tool_handlers):
    """
    Run a Gemma 4 agent that can call tools.
    
    tool_handlers: dict mapping function name → async callable
    """
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    
    # Loop: Gemma 4 may call tools, we execute them, feed results back
    max_iterations = 5
    for _ in range(max_iterations):
        response = await call_gemma4(messages, tools=tools)
        
        tool_calls = extract_tool_calls(response)
        
        if not tool_calls:
            # No tool calls — agent is done, return text response
            return extract_text(response)
        
        # Append the assistant message with tool calls
        messages.append(response["choices"][0]["message"])
        
        # Execute each tool call and append results
        for tc in tool_calls:
            fn_name = tc["function"]["name"]
            fn_args = json.loads(tc["function"]["arguments"])
            
            handler = tool_handlers.get(fn_name)
            if handler:
                result = await handler(**fn_args)
            else:
                result = {"error": f"Unknown tool: {fn_name}"}
            
            messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": json.dumps(result),
            })
    
    # If we hit max iterations, return whatever we have
    return extract_text(response)
```

### 3.3 The orchestrator (`app/agents/orchestrator.py`)

```python
"""
Orchestrator: runs all agents concurrently and streams status via SSE.
"""
import asyncio
import json
from typing import AsyncGenerator

from app.agents.fema_agent import run_fema_agent
from app.agents.local_agent import run_local_agent
from app.agents.weather_agent import run_weather_agent
from app.agents.news_agent import run_news_agent
from app.agents.archive_agent import run_archive_agent
from app.agents.risk_agent import run_risk_agent
from app.agents.advisor_agent import run_advisor_agent
from app.tools.geocoder import geocode_address


async def run_assessment(address: str) -> AsyncGenerator[str, None]:
    """
    Run full flood risk assessment. Yields SSE events.
    
    Flow:
    1. Geocode the address
    2. Run data-fetcher agents in parallel (FEMA, 311, weather, news, archive)
    3. Run risk analyst agent (needs all data)
    4. Run advisor agent (needs risk analysis)
    5. Yield final dossier
    """
    # Step 0: Geocode
    geo = await geocode_address(address)
    if not geo:
        yield sse_event("error", {"message": "Could not geocode address"})
        return
    
    lat, lon = geo["lat"], geo["lon"]
    display_name = geo["display_name"]
    city = geo.get("city", "")
    state = geo.get("state", "")
    county = geo.get("county", "")
    
    yield sse_event("geocoded", {
        "address": display_name,
        "lat": lat,
        "lon": lon,
    })
    
    # Step 1: Run data-fetcher agents in parallel
    # Each agent function should:
    #   - Accept (lat, lon, city, state, county) as needed
    #   - Return a dict with its findings
    #   - Handle its own errors gracefully (return partial data, not crash)
    
    agent_tasks = {
        "fema": run_fema_agent(lat, lon),
        "local": run_local_agent(lat, lon, city, state),
        "weather": run_weather_agent(lat, lon),
        "news": run_news_agent(city, state, lat, lon),
        "archive": run_archive_agent(county, state, lat, lon),
    }
    
    # Stream status as each agent starts
    for name in agent_tasks:
        yield sse_event("agent_update", {
            "agent": name,
            "status": "working",
            "summary": f"Investigating...",
        })
    
    # Run all data agents concurrently
    results = {}
    done_tasks = {}
    
    for coro_name, coro in agent_tasks.items():
        done_tasks[coro_name] = asyncio.create_task(coro)
    
    # As each completes, yield an update
    for coro_name, task in done_tasks.items():
        try:
            result = await task
            results[coro_name] = result
            yield sse_event("agent_update", {
                "agent": coro_name,
                "status": "done",
                "summary": result.get("summary", "Complete"),
            })
        except Exception as e:
            results[coro_name] = {"error": str(e), "summary": f"Error: {str(e)[:100]}"}
            yield sse_event("agent_update", {
                "agent": coro_name,
                "status": "error",
                "summary": f"Error: {str(e)[:100]}",
            })
    
    # Step 2: Risk analyst (needs all data, uses Gemma 4 reasoning)
    yield sse_event("agent_update", {
        "agent": "risk",
        "status": "working",
        "summary": "Analyzing risk factors...",
    })
    
    try:
        risk_result = await run_risk_agent(results, lat, lon, display_name)
        results["risk"] = risk_result
        yield sse_event("agent_update", {
            "agent": "risk",
            "status": "done",
            "summary": risk_result.get("summary", "Analysis complete"),
        })
    except Exception as e:
        results["risk"] = {"error": str(e)}
        yield sse_event("agent_update", {
            "agent": "risk",
            "status": "error",
            "summary": str(e)[:100],
        })
    
    # Step 3: Advisor agent (needs risk analysis)
    yield sse_event("agent_update", {
        "agent": "advisor",
        "status": "working",
        "summary": "Generating recommendations...",
    })
    
    try:
        advisor_result = await run_advisor_agent(results, display_name)
        results["advisor"] = advisor_result
        yield sse_event("agent_update", {
            "agent": "advisor",
            "status": "done",
            "summary": advisor_result.get("summary", "Recommendations ready"),
        })
    except Exception as e:
        results["advisor"] = {"error": str(e)}
        yield sse_event("agent_update", {
            "agent": "advisor",
            "status": "error",
            "summary": str(e)[:100],
        })
    
    # Step 4: Compile final dossier
    dossier = compile_dossier(display_name, lat, lon, results)
    yield sse_event("complete", {"dossier": dossier})


def sse_event(event_type: str, data: dict) -> str:
    """Format an SSE event string."""
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


def compile_dossier(address, lat, lon, results):
    """Compile all agent results into the final dossier structure."""
    return {
        "address": address,
        "coordinates": {"lat": lat, "lon": lon},
        "fema": results.get("fema", {}),
        "local": results.get("local", {}),
        "weather": results.get("weather", {}),
        "news": results.get("news", {}),
        "archive": results.get("archive", {}),
        "risk": results.get("risk", {}),
        "advisor": results.get("advisor", {}),
    }
```

### 3.4 SSE endpoint (`app/api/assess.py`)

```python
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from app.agents.orchestrator import run_assessment

router = APIRouter()

class AssessRequest(BaseModel):
    address: str

@router.post("/api/assess")
async def assess(req: AssessRequest):
    async def event_generator():
        async for event in run_assessment(req.address):
            yield event
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
```

### 3.5 Example agent implementation: FEMA agent

```python
"""
FEMA expert agent — looks up flood zone via FEMA NFHL ArcGIS REST API.

This agent demonstrates the pattern:
1. Call the external API tool directly (no LLM needed for data fetch)
2. Feed the raw data to Gemma 4 for interpretation
3. Return structured findings
"""
import json
from app.tools.fema import lookup_fema_flood_zone
from app.llm.client import call_gemma4, extract_text
from app.llm.prompts import FEMA_AGENT_SYSTEM_PROMPT


async def run_fema_agent(lat: float, lon: float) -> dict:
    # Step 1: Fetch data from FEMA API
    fema_data = await lookup_fema_flood_zone(lat, lon)
    
    if not fema_data or fema_data.get("error"):
        return {
            "flood_zone": "unknown",
            "is_sfha": False,
            "summary": "Could not retrieve FEMA flood zone data",
            "raw": fema_data,
        }
    
    # Step 2: Ask Gemma 4 to interpret the FEMA data
    user_prompt = f"""Interpret this FEMA flood zone data for coordinates ({lat}, {lon}):

{json.dumps(fema_data, indent=2)}

Return a JSON object with these fields:
- flood_zone: the zone code (e.g. "X", "AE", "VE")
- zone_description: what this zone means in plain English
- is_sfha: boolean, whether this is a Special Flood Hazard Area
- requires_insurance: boolean, whether federal law mandates flood insurance
- base_flood_elevation: number or null
- map_date: the FIRM panel effective date if available
- gap_warning: string or null — if the zone is X but the location is in a known urban flooding area (flat terrain, combined sewers), note that FEMA maps may not reflect actual risk
- summary: a 1-sentence finding for the status feed

Return ONLY the JSON object, no other text."""

    response = await call_gemma4(
        messages=[
            {"role": "system", "content": FEMA_AGENT_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.1,
    )
    
    text = extract_text(response)
    
    try:
        # Parse the JSON from Gemma's response
        # Strip markdown fences if present
        clean = text.strip().removeprefix("```json").removesuffix("```").strip()
        result = json.loads(clean)
        result["raw"] = fema_data
        return result
    except json.JSONDecodeError:
        return {
            "flood_zone": fema_data.get("FLD_ZONE", "unknown"),
            "is_sfha": fema_data.get("FLD_ZONE", "X") in ("A", "AE", "AH", "AO", "V", "VE"),
            "summary": f"Zone {fema_data.get('FLD_ZONE', 'unknown')}",
            "raw": fema_data,
            "interpretation_raw": text,
        }
```

### 3.6 Risk analyst agent (the showcase for Gemma 4 reasoning)

```python
"""
Risk analyst agent — THE key Gemma 4 showcase.
Uses reasoning mode (thinking=ON) to synthesize all data into a risk score.
This is what impresses the hackathon judges.
"""
import json
from app.llm.client import call_gemma4, extract_text, extract_reasoning
from app.llm.prompts import RISK_AGENT_SYSTEM_PROMPT


async def run_risk_agent(all_data: dict, lat: float, lon: float, address: str) -> dict:
    user_prompt = f"""You are analyzing flood risk for: {address} ({lat}, {lon})

Here is all the data collected by our investigation team:

## FEMA Expert Findings
{json.dumps(all_data.get('fema', {}), indent=2, default=str)}

## Local Infrastructure Findings (311 data, sewer type)
{json.dumps(all_data.get('local', {}), indent=2, default=str)}

## Weather & Hydrology Findings
{json.dumps(all_data.get('weather', {}), indent=2, default=str)}

## Recent Local Flood News
{json.dumps(all_data.get('news', {}), indent=2, default=str)}

## Historical Storm Archive
{json.dumps(all_data.get('archive', {}), indent=2, default=str)}

---

TASK: Synthesize all of this data into a flood risk assessment.

IMPORTANT CONTEXT:
- A "100-year flood" means 1% annual exceedance probability (AEP), NOT once per century
- Formula: P(at least one event in n years) = 1 - (1 - AEP)^n
- Over a 30-year mortgage: 1% AEP → 26% cumulative probability
- FEMA flood maps ONLY measure riverine/coastal flooding
- In cities with combined sewer systems, most flooding is basement sewer backup — FEMA does NOT map this
- If there are many 311 flood reports but FEMA says "minimal risk", the FEMA designation is misleading
- Chicago's sewer system overwhelms after ~0.67 inches of rain per hour

Return a JSON object with:
{{
  "risk_score": <0-100 integer>,
  "risk_level": "low" | "medium" | "high",
  "aep_estimate": <estimated annual exceedance probability as decimal, e.g. 0.04>,
  "mortgage_30yr_probability": <cumulative probability over 30 years, e.g. 0.68>,
  "fema_gap_explanation": "<2-3 sentences explaining if/why FEMA designation is misleading>",
  "key_risk_factors": ["<ranked list of top risk factors>"],
  "mitigating_factors": ["<factors that reduce risk>"],
  "summary": "<1 sentence for the status feed>"
}}

Think step by step. Show your reasoning. Return ONLY the JSON object at the end."""

    # THIS IS THE KEY: reasoning=True enables Gemma 4's thinking mode
    # The judges want to see this capability used
    response = await call_gemma4(
        messages=[
            {"role": "system", "content": RISK_AGENT_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        reasoning=True,  # <-- Gemma 4 thinking mode
        temperature=0.2,
        max_tokens=8192,  # reasoning needs more tokens
    )
    
    text = extract_text(response)
    reasoning = extract_reasoning(response)
    
    try:
        clean = text.strip().removeprefix("```json").removesuffix("```").strip()
        result = json.loads(clean)
        result["reasoning_trace"] = reasoning  # Save for writeup/demo
        return result
    except json.JSONDecodeError:
        return {
            "risk_score": 50,
            "risk_level": "medium",
            "summary": "Risk analysis completed with partial data",
            "raw_response": text,
            "reasoning_trace": reasoning,
        }
```

---

## 4. Tool implementations (data fetchers)

Each tool is a simple async function that calls a free public API.

### FEMA NFHL (`app/tools/fema.py`)
```python
import httpx

FEMA_BASE = "https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28/query"

async def lookup_fema_flood_zone(lat: float, lon: float) -> dict:
    params = {
        "geometry": f'{{"x":{lon},"y":{lat},"spatialReference":{{"wkid":4326}}}}',
        "geometryType": "esriGeometryPoint",
        "inSR": "4326",
        "outFields": "FLD_ZONE,STATIC_BFE,ZONE_SUBTY,DFIRM_ID,VERSION_ID",
        "returnGeometry": "false",
        "f": "json",
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(FEMA_BASE, params=params)
        data = resp.json()
    
    features = data.get("features", [])
    if not features:
        return {"FLD_ZONE": "UNMAPPED", "note": "No FEMA data for this location"}
    
    return features[0].get("attributes", {})
```

### Chicago 311 (`app/tools/chicago_311.py`)
```python
import httpx

CHICAGO_311_BASE = "https://data.cityofchicago.org/resource/v6vf-nfxy.json"

async def get_flood_reports(lat: float, lon: float, radius_m: int = 500, years: int = 5) -> dict:
    from datetime import datetime, timedelta
    since = (datetime.now() - timedelta(days=365 * years)).strftime("%Y-%m-%dT00:00:00")
    
    query = (
        f"$where=sr_short_code in('WIB','SFL') "
        f"AND created_date > '{since}' "
        f"AND within_circle(location, {lat}, {lon}, {radius_m})"
        f"&$limit=1000"
        f"&$select=sr_short_code,created_date,street_address,ward"
    )
    
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{CHICAGO_311_BASE}?{query}")
        reports = resp.json()
    
    basement = [r for r in reports if r.get("sr_short_code") == "WIB"]
    street = [r for r in reports if r.get("sr_short_code") == "SFL"]
    
    return {
        "total_reports": len(reports),
        "basement_flooding": len(basement),
        "street_flooding": len(street),
        "radius_m": radius_m,
        "since": since,
        "recent_reports": reports[:10],  # First 10 for context
    }
```

### USGS stream gauges (`app/tools/usgs.py`)
```python
import httpx

async def find_nearest_gauge(lat: float, lon: float) -> dict:
    """Find the nearest active USGS stream gauge."""
    delta = 0.1  # ~10km search box
    url = "https://waterservices.usgs.gov/nwis/site/"
    params = {
        "format": "json",
        "bBox": f"{lon-delta},{lat-delta},{lon+delta},{lat+delta}",
        "siteType": "ST",
        "siteStatus": "active",
        "hasDataTypeCd": "iv",
    }
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(url, params=params)
        data = resp.json()
    
    sites = data.get("value", {}).get("timeSeries", [])
    if not sites:
        # Try wider search
        delta = 0.3
        params["bBox"] = f"{lon-delta},{lat-delta},{lon+delta},{lat+delta}"
        resp = await client.get(url, params=params)
        data = resp.json()
        sites = data.get("value", {}).get("timeSeries", [])
    
    # Return first site (simplification)
    site_info = data.get("value", {}).get("queryInfo", {})
    return data


async def get_current_streamflow(site_id: str) -> dict:
    """Get current streamflow and gage height."""
    url = "https://waterservices.usgs.gov/nwis/iv/"
    params = {
        "format": "json",
        "sites": site_id,
        "parameterCd": "00060,00065",  # discharge, gage height
        "siteStatus": "all",
    }
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(url, params=params)
    return resp.json()
```

### NOAA NWS (`app/tools/noaa.py`)
```python
import httpx

HEADERS = {"User-Agent": "(floodiq.pages.dev, contact@floodiq.dev)"}

async def get_forecast(lat: float, lon: float) -> dict:
    """Get NOAA weather forecast and active alerts."""
    async with httpx.AsyncClient(timeout=20, headers=HEADERS) as client:
        # Step 1: Get grid point
        points_resp = await client.get(f"https://api.weather.gov/points/{lat},{lon}")
        points = points_resp.json()
        
        forecast_url = points.get("properties", {}).get("forecast", "")
        alerts_url = f"https://api.weather.gov/alerts/active?point={lat},{lon}"
        
        # Step 2: Get forecast + alerts in parallel
        forecast_resp = await client.get(forecast_url) if forecast_url else None
        alerts_resp = await client.get(alerts_url)
        
        return {
            "forecast": forecast_resp.json() if forecast_resp else {},
            "alerts": alerts_resp.json().get("features", []),
        }
```

### Open-Meteo flood (`app/tools/open_meteo.py`)
```python
import httpx

async def get_flood_forecast(lat: float, lon: float) -> dict:
    url = "https://flood-api.open-meteo.com/v1/flood"
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": "river_discharge,river_discharge_max",
        "past_days": 30,
    }
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(url, params=params)
    return resp.json()
```

### GDELT news (`app/tools/gdelt.py`)
```python
import httpx

async def search_flood_news(city: str, state: str, max_results: int = 5) -> list[dict]:
    query = f'"basement flooding" OR "sewer backup" OR "flood damage" {city}'
    url = "https://api.gdeltproject.org/api/v2/doc/doc"
    params = {
        "query": query,
        "mode": "ArtList",
        "format": "json",
        "maxrecords": max_results,
        "timespan": "6m",
    }
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(url, params=params)
        data = resp.json()
    
    articles = data.get("articles", [])
    return [
        {
            "title": a.get("title", ""),
            "source": a.get("domain", ""),
            "date": a.get("seendate", "")[:10],
            "url": a.get("url", ""),
        }
        for a in articles
    ]
```

### Geocoder (`app/tools/geocoder.py`)
```python
import httpx

async def geocode_address(address: str) -> dict | None:
    url = "https://nominatim.openstreetmap.org/search"
    params = {
        "q": address,
        "format": "json",
        "limit": 1,
        "addressdetails": 1,
    }
    headers = {"User-Agent": "FloodIQ/1.0 (floodiq.pages.dev)"}
    
    async with httpx.AsyncClient(timeout=15, headers=headers) as client:
        resp = await client.get(url, params=params)
        results = resp.json()
    
    if not results:
        return None
    
    r = results[0]
    addr = r.get("address", {})
    return {
        "lat": float(r["lat"]),
        "lon": float(r["lon"]),
        "display_name": r.get("display_name", address),
        "city": addr.get("city") or addr.get("town") or addr.get("village", ""),
        "state": addr.get("state", ""),
        "county": addr.get("county", ""),
    }
```

---

## 5. System prompts (`app/llm/prompts.py`)

```python
FEMA_AGENT_SYSTEM_PROMPT = """You are a FEMA flood zone expert. Your job is to interpret FEMA National Flood Hazard Layer data and explain what it means for a property owner.

Key knowledge:
- Zone X (unshaded) = minimal flood risk, no insurance required
- Zone X (shaded) = 0.2% annual chance (500-year flood)
- Zone A, AE = 1% annual chance (100-year flood), SFHA, insurance required for federally backed mortgages
- Zone V, VE = coastal high hazard, 1% annual chance with wave action
- FEMA maps primarily measure RIVERINE and COASTAL flooding
- Urban flooding from sewer backup is NOT reflected in FEMA zones
- Many FIRM panels are 10-20+ years old and may not reflect current risk

Always respond with valid JSON only."""

RISK_AGENT_SYSTEM_PROMPT = """You are a flood risk analyst specializing in urban flood risk assessment. You synthesize data from multiple sources (FEMA, municipal 311 reports, USGS stream gauges, weather forecasts, historical storm events, and news) into a comprehensive risk score.

Critical knowledge:
- "100-year flood" = 1% Annual Exceedance Probability (AEP), NOT once per century
- P(at least 1 flood in n years) = 1 - (1 - AEP)^n
- 1% AEP over 30 years = 26% chance. Over 80-year lifetime = 55% chance.
- In flat cities with combined sewer systems, FEMA zones dramatically UNDERSTATE risk
- Chicago's combined sewers overwhelm after ~0.67 in/hr of rain
- 42% of Cook County is impervious surface
- MWRD's Deep Tunnel (TARP) has 17.5B gallon capacity but local sewers still bottleneck
- 311 basement flooding reports are a strong signal of actual urban flood risk, even in Zone X

Think step by step. Use the AEP formula. Be specific with numbers.
Always respond with valid JSON only."""

ADVISOR_AGENT_SYSTEM_PROMPT = """You are a flood insurance and mitigation advisor. You translate technical flood risk data into specific, actionable recommendations for homeowners and renters.

Key knowledge:
- NFIP Preferred Risk Policy: available in Zone X, ~$400-600/yr, covers building+contents up to $250K/$100K
- NFIP Standard: for SFHAs, costs vary by zone and building
- Sewer backup rider: add-on to homeowners policy, ~$40-75/yr, covers the #1 cause of Chicago flooding
- Parametric insurance (FloodFlash model): sensor-triggered instant payout, pre-agreed trigger depth and amount
  - Basis risk = mismatch between trigger event and actual loss
  - Best for business interruption coverage
- Private excess flood: fills gaps above NFIP limits
- Key mitigation actions (prioritized by cost-effectiveness):
  1. Disconnect downspouts (free, DIY) — Chicago DWM: 312-747-7030
  2. Install backwater valve ($1K-2.5K) — check MWRD cost-share programs
  3. Sewer camera inspection ($150-300)
  4. Rain barrels ($22.30 from MWRD)
  5. Permeable pavement for patios/walkways
  6. CNT RainReady home assessment (free)

Write at a 5th-grade reading level. No jargon without explanation.
Always respond with valid JSON only."""

NEWS_AGENT_SYSTEM_PROMPT = """You are a flood news researcher. Given recent news articles about flooding in a specific area, summarize the key findings that are relevant to a homeowner's flood risk assessment.

Focus on: recent flood events, infrastructure failures, insurance cost changes, government programs, community initiatives.
Ignore: national policy debates, unrelated weather events, opinion pieces without data.
Always respond with valid JSON only."""

ARCHIVE_AGENT_SYSTEM_PROMPT = """You are a flood history archivist. You analyze historical storm event records and FEMA disaster declarations to establish the flooding track record for a specific area.

Focus on: frequency of events, severity trends, types of flooding (flash flood vs riverine vs urban), property damage patterns.
Always respond with valid JSON only."""
```

---

## 6. FastAPI main app (`app/main.py`)

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.assess import router as assess_router
from app.api.health import router as health_router

app = FastAPI(title="FloodIQ API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https?://(localhost:\d+|.*\.pages\.dev|.*\.hf\.space)",
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(assess_router)
app.include_router(health_router)
```

---

## 7. Deployment files

### `requirements.txt`
```
fastapi==0.115.0
uvicorn[standard]==0.32.0
httpx==0.28.0
pydantic==2.10.0
```

### `Dockerfile`
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ ./app/
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### `README.md` (HF Spaces frontmatter)
```
---
title: FloodIQ API
emoji: 🌊
colorFrom: blue
colorTo: teal
sdk: docker
app_port: 8000
pinned: false
---

FloodIQ backend — multi-agent flood risk assessment powered by Gemma 4.
```

---

## 8. Environment variables

```
OPENROUTER_API_KEY=sk-or-v1-...    # Get free at openrouter.ai/settings/keys
GOOGLE_AI_KEY=...                   # Optional fallback, get at aistudio.google.com
```

---

## 9. Frontend SSE integration

The frontend should connect like this:

```typescript
// useFloodAssessment.ts
async function runAssessment(address: string) {
  const response = await fetch(`${API_URL}/api/assess`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ address }),
  });

  const reader = response.body?.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader!.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n\n');
    buffer = lines.pop() || '';

    for (const block of lines) {
      const eventMatch = block.match(/^event: (.+)$/m);
      const dataMatch = block.match(/^data: (.+)$/m);
      if (eventMatch && dataMatch) {
        const eventType = eventMatch[1];
        const data = JSON.parse(dataMatch[1]);
        
        switch (eventType) {
          case 'agent_update':
            // Update agent status in UI
            updateAgentStatus(data.agent, data.status, data.summary);
            break;
          case 'complete':
            // Render the full dossier
            setDossier(data.dossier);
            break;
          case 'error':
            setError(data.message);
            break;
        }
      }
    }
  }
}
```

---

## 10. Testing locally

```bash
# Terminal 1: Backend
cd backend
pip install -r requirements.txt
export OPENROUTER_API_KEY="sk-or-v1-..."
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

# Terminal 2: Test the endpoint
curl -N -X POST http://localhost:8000/api/assess \
  -H "Content-Type: application/json" \
  -d '{"address": "4521 S Drexel Blvd, Chicago IL"}'

# Terminal 3: Frontend
cd frontend
npm run dev
# Set VITE_API_URL=http://localhost:8000 in .env
```

---

## 11. Hackathon alignment checklist

```
[x] Uses Gemma 4 as the primary LLM (OpenRouter free tier)
[x] Demonstrates native function calling (agents use tools)
[x] Demonstrates reasoning/thinking mode (risk analyst agent)
[x] Demonstrates agentic workflows (7 agents, orchestrator pattern)
[x] Solves a real-world problem (flood risk communication gap)
[x] Works as a live demo (publicly accessible, no login required)
[x] Uses free, public data sources (FEMA, NOAA, USGS, Chicago 311, GDELT)
[x] Track: Global Resilience
[x] Multi-agent architecture is clearly documented
[x] All code will be in public GitHub repo
```
