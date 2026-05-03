---
name: flutiq
description: >
  FlutIQ is a multi-agent flood risk assessment app for the Gemma 4 Good Hackathon.
  Use this skill whenever working on the FlutIQ project — building, debugging, or
  extending the React frontend, FastAPI backend, Gemma 4 agent system, data tool
  integrations, SSE streaming, deployment to Cloudflare Pages / HF Spaces, or
  preparing hackathon deliverables (video script, Kaggle writeup, README).
  Trigger on any mention of FlutIQ, flood risk agents, FEMA gap analysis,
  Gemma 4 function calling, parametric insurance, or the hackathon submission.
---

# FlutIQ Development Skill

## What is FlutIQ

A multi-agent AI flood risk advisor. User enters a US address → 7 specialized Gemma 4 agents investigate in parallel → user receives a personalized "risk dossier" explaining their actual flood risk, what insurance they need, and what actions to take.

Built for the **Gemma 4 Good Hackathon** (Kaggle, deadline May 18, 2026). Track: Global Resilience.

## Architecture at a glance

```
React (Cloudflare Pages) → FastAPI (HF Spaces) → Gemma 4 (OpenRouter free)
                                    │
                    ┌───────────────┼───────────────┐
                    ▼               ▼               ▼
              Data agents      Risk analyst     Advisor agent
              (parallel)       (reasoning ON)   (recommendations)
                    │
         ┌────┬────┬────┬────┐
         ▼    ▼    ▼    ▼    ▼
       FEMA  311  USGS GDELT NOAA
```

## Critical rules

1. **Gemma 4 is the ONLY LLM.** Never use GPT, Claude, or any other model in the codebase. The hackathon requires Gemma 4.
2. **OpenRouter free tier** is the primary inference path. Model IDs:
   - `google/gemma-4-31b-it:free` (primary)
   - `google/gemma-4-26b-a4b-it:free` (fallback)
3. **All data sources must be free and require no API key** (except OpenRouter itself). FEMA, USGS, NOAA NWS, Open-Meteo, Chicago 311, GDELT — all free.
4. **SSE (Server-Sent Events)** for streaming agent status to the frontend. Not WebSocket.
5. **No database.** Everything computed per-request. In-memory cache only.
6. **The risk analyst agent MUST use reasoning mode** (`reasoning: {enabled: true}` in the OpenRouter request). This is the key Gemma 4 feature showcase.
7. **JSON output from agents.** Every agent prompt ends with "Return ONLY the JSON object, no other text." Parse with markdown fence stripping.
8. **Error handling must be graceful.** If an agent fails, the others continue. Partial dossiers are better than crashes.

## Key files and their purpose

### Frontend (React + TypeScript + Tailwind)
- `src/components/SearchScreen.tsx` — Landing page with address input
- `src/components/AgentsScreen.tsx` — Shows agents working with live status
- `src/components/DossierScreen.tsx` — Final risk report with collapsible sections
- `src/hooks/useFloodAssessment.ts` — SSE connection to backend

### Backend (Python + FastAPI)
- `app/main.py` — FastAPI app with CORS
- `app/api/assess.py` — `POST /api/assess` SSE endpoint
- `app/agents/orchestrator.py` — Runs all agents, streams updates
- `app/agents/fema_agent.py` — FEMA flood zone lookup
- `app/agents/local_agent.py` — Chicago 311 + sewer infrastructure
- `app/agents/weather_agent.py` — USGS + NOAA + Open-Meteo
- `app/agents/news_agent.py` — GDELT flood news search
- `app/agents/archive_agent.py` — NOAA Storm Events history
- `app/agents/risk_agent.py` — Risk scoring with Gemma 4 reasoning (CRITICAL)
- `app/agents/advisor_agent.py` — Insurance recs + action plan
- `app/llm/client.py` — OpenRouter Gemma 4 client
- `app/llm/prompts.py` — System prompts for each agent
- `app/tools/*.py` — Data fetcher functions (one per API)

## Gemma 4 via OpenRouter — how to call

```python
import httpx

async def call_gemma4(messages, tools=None, reasoning=False):
    payload = {
        "model": "google/gemma-4-31b-it:free",
        "messages": messages,
        "max_tokens": 4096,
        "temperature": 0.3,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    if reasoning:
        payload["reasoning"] = {"enabled": True}
    
    async with httpx.AsyncClient(timeout=90) as client:
        resp = await client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        return resp.json()
```

### Function calling format (OpenAI-compatible)

```python
tools = [{
    "type": "function",
    "function": {
        "name": "lookup_fema_flood_zone",
        "description": "Look up FEMA flood zone for coordinates",
        "parameters": {
            "type": "object",
            "properties": {
                "latitude": {"type": "number"},
                "longitude": {"type": "number"}
            },
            "required": ["latitude", "longitude"]
        }
    }
}]
```

### Reasoning mode

Only the **risk analyst agent** uses reasoning. Set `"reasoning": {"enabled": true}` in the request. Extract reasoning from `response.choices[0].message.reasoning_details`.

### Rate limit handling

OpenRouter free: ~20 RPM / 200 RPD per model. On 429, retry with fallback model `google/gemma-4-26b-a4b-it:free`, then exponential backoff.

## SSE event format

```
event: agent_update
data: {"agent": "fema", "status": "working", "summary": "Investigating..."}

event: agent_update
data: {"agent": "fema", "status": "done", "summary": "Zone X — minimal..."}

event: complete
data: {"dossier": { ... full report JSON }}

event: error
data: {"message": "Could not geocode address"}
```

## Free data APIs quick reference

| API | Endpoint | Auth |
|-----|----------|------|
| FEMA NFHL | `hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28/query` | None |
| Chicago 311 | `data.cityofchicago.org/resource/v6vf-nfxy.json` | None |
| USGS Water | `waterservices.usgs.gov/nwis/iv/` | None |
| NOAA NWS | `api.weather.gov/points/{lat},{lon}` | None (set User-Agent) |
| Open-Meteo | `flood-api.open-meteo.com/v1/flood` | None |
| GDELT | `api.gdeltproject.org/api/v2/doc/doc` | None |
| Elevation | `epqs.nationalmap.gov/v1/json` | None |
| Nominatim | `nominatim.openstreetmap.org/search` | None (set User-Agent) |

## Deployment

- Frontend: Cloudflare Pages (free, `npm run build`, output `dist`)
- Backend: HF Spaces Docker SDK (free, port 8000)
- Environment: `OPENROUTER_API_KEY` in HF Spaces secrets

## Hackathon deliverables

1. **Live demo** — publicly accessible, no login
2. **Public GitHub repo** — well-documented
3. **YouTube video** — ≤3 min, storytelling-first
4. **Kaggle Writeup** — ≤1,500 words, track: Global Resilience

## Domain knowledge

### The core insight
FEMA flood maps measure riverine/coastal flooding. In flat cities like Chicago with combined sewer systems, most flooding is sewer backup — which FEMA doesn't map. People outside FEMA flood zones don't buy flood insurance, then get devastated.

### The "500-year flood" misconception
- 100-year flood = 1% annual exceedance probability (AEP)
- P(at least 1 event in n years) = 1 − (1 − AEP)^n
- Over 30-year mortgage: 1% AEP → 26% chance
- 500-year flood (0.2% AEP) over 30 years → 6% chance

### Chicago-specific
- Combined sewer system overwhelms after ~0.67 in/hr
- 42% of Cook County is impervious surface
- MWRD Deep Tunnel (TARP): 109 miles of tunnels, 17.5B gallon capacity
- Local sewers still bottleneck even when TARP has capacity
- CNT RainReady: free homeowner flood assessment tool
- Key mitigation: disconnect downspouts, backwater valve, sewer backup rider

### Parametric insurance (FloodFlash model)
- Sensor-triggered payout at pre-agreed depth
- Pays within 48 hours, no adjuster
- Basis risk = mismatch between trigger and actual loss
- Best for business interruption, excess over NFIP

## Reference documents

For detailed specifications, read:
- `FLOODIQ_DESIGN_SPEC.md` — full UX specification, visual design system, all 3 screens
- `FLOODIQ_BACKEND_SPEC.md` — complete backend architecture, agent implementations, tool code, system prompts, deployment files
