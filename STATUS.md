# FlutIQ — current state (2026-05-06, v0.14.1)

A working snapshot of what's built, what wobbles, and what's left.
This is a build journal, not a polished README — the README at the
repo root is the public landing page.

---

## What FlutIQ is

A multi-agent flood-risk advisor for the **Gemma 4 Good Hackathon**
(Kaggle, deadline May 18, 2026, Global Resilience track).

Mission: **reduce the complexity and scariness of insurance**, not
just compute a flood risk score. The technical pitch (FEMA-gap,
multimodal Gemma 4, multi-agent orchestration) is the vehicle; the
goal is making a homeowner feel less overwhelmed about flood-insurance
decisions.

User flow: enter a US address → 9 specialist Gemma 4 agents investigate
in parallel → user gets a personalized dossier with verified insurance
options, a prioritized action plan, a multimodal explanation of why
FEMA's flood map isn't the whole story, and a county-level multi-hazard
context (wildfire, hurricane, tornado, etc.) for the wider neighborhood.

Live at: **https://kredd25-flutiq.hf.space**
GitHub: https://github.com/kredd2506/Gemma4Good_FlutIQ

---

## What's working end-to-end

```
POST /api/assess
  → geocode (Nominatim → Census FIPS fallback)
  → 7 data agents in parallel (5 text + 2 vision)
  → risk-analyst (Gemma 4 reasoning + 2 raw images + 7 text findings,
                  one inference call)
  → advisor (catalog-driven, multilingual, multi-hazard aware)
  → compiled dossier streamed via SSE
```

All 9 agents return structured JSON. Per-agent updates stream live
to the React frontend. Typical assessment time: ~30–60s end-to-end
(Gemma 4 vision calls dominate; the text agents finish in ~5s).

Verified passing flows across geographies and hazard mixes:

| Address | What renders |
|---|---|
| 4521 S Drexel Blvd, **Chicago IL** | FEMA Zone X · 89 permits/$190M (densification) · NRI top hazards: Cold wave + Tornado + Heat wave |
| 1500 Allen Pkwy, **Houston TX** | FEMA Zone AE Floodway · NRI hurricane Very High · risk score 95 |
| 350 5th Ave, **New York NY** | NRI Manhattan multi-hazard · 311 sewer reports · classic CSO pattern |
| 2570 24th St, **San Francisco CA** | Mission · 595 sewer reports + $50M permits, **trend increasing, concern: high** |
| 1 World Way, **Los Angeles CA** | Permits-only ($320M including $99M downtown project) · NRI Wildfire + Earthquake Very High · Community Resilience Very Low |
| 1100 Congress Ave, **Austin TX** | Flood-coded 311 + permit count · NRI Texas heat/tornado profile |
| 1133 Potomac Rd, **Atlanta GA** | Property + NRI works; gracefully says "no 311/permits wired for this city" |

---

## Architecture

```
React (backend/static/index.html, Babel-standalone, ~1700 lines)
  │
  └─ POST /api/assess  ──── SSE ────►  FastAPI / uvicorn (Python 3.13)
                                          │
                                          ▼
                                Geocoder (Nominatim → Census)
                                          │
                                          ▼
                       Orchestrator (asyncio + parallel fan-out)
                       ┌──────┬─────┬───────┬──────┬─────────┬──────────┬───────────┐
                       ▼      ▼     ▼       ▼      ▼         ▼          ▼           ▼
                     FEMA  Local Weather  News Archive    Regional  Satellite  StreetView
                    NFHL  311+   USGS+   GDELT GDELT    NRI county  Mapbox+   GoogleSV+
                          permits NOAA+   6mo   24mo    18 hazards  Gemma4    Gemma4
                                Open-Meteo                          vision    vision
                                                                    + bbox    + bbox
                       │      │     │       │      │         │          │           │
                       └──────┴─────┴───────┴──────┴─────────┴──────────┴──────┬────┘
                                                                                │
                                                              text findings + raw images
                                                                                ▼
                                                  Risk Analyst (Gemma 4 reasoning + multimodal)
                                                  · 2 images + 7 data sources
                                                  · ONE inference call
                                                  · CoT trace cites which layer each claim is from
                                                                                │
                                                                                ▼
                                                  Advisor (catalog-driven, multilingual)
                                                                                │
                                                                                ▼
                                                                          Dossier JSON
```

### Files & purpose

```
backend/
├── app/
│   ├── main.py                FastAPI + CORS + static mount
│   ├── config.py              env + model IDs + 3rd-party keys
│   ├── api/
│   │   ├── health.py          GET /api/health
│   │   └── assess.py          POST /api/assess (SSE)
│   ├── agents/                                       # 9 agents
│   │   ├── orchestrator.py    parallel-then-sequential runner
│   │   ├── fema_agent.py      property-level FEMA flood zone
│   │   ├── local_agent.py     city-aware: 311 + building permits
│   │   ├── weather_agent.py   USGS + NOAA + Open-Meteo
│   │   ├── news_agent.py      GDELT 6mo
│   │   ├── archive_agent.py   GDELT 24mo (Storm Events DB proxy)
│   │   ├── regional_risk_agent.py  FEMA NRI county multi-hazard
│   │   ├── satellite_agent.py    Mapbox + Gemma 4 vision + bbox
│   │   ├── streetview_agent.py   Google SV + Gemma 4 vision + bbox
│   │   ├── risk_agent.py      multimodal synthesis (2 imgs + 7 data)
│   │   └── advisor_agent.py   catalog-driven, multilingual, multi-hazard aware
│   ├── tools/
│   │   ├── geocoder.py        Nominatim → Census (county FIPS)
│   │   ├── fema.py            FEMA NFHL ArcGIS REST
│   │   ├── chicago_311.py     Socrata SODA — generic, city-aware
│   │   ├── building_permits.py Socrata — new construction + reno
│   │   ├── nri_county.py      FEMA NRI via RAPT ArcGIS REST
│   │   ├── streetview.py      Google SV Static (metadata-first, bearing-aimed)
│   │   ├── mapbox.py          Mapbox Static Images (satellite + outdoors)
│   │   ├── usgs.py            stream gauges
│   │   ├── noaa.py            forecast + flood alerts
│   │   ├── open_meteo.py      flood + precipitation
│   │   └── gdelt.py           DOC API + per-IP rate-limit lock
│   ├── llm/
│   │   ├── client.py          OpenRouter wrapper, 429+5xx retries
│   │   └── prompts.py         layered-signal system prompts
│   └── data/
│       ├── cities.py              5-city Tier-1 registry
│       ├── insurance_catalog.py   curated REAL products
│       └── languages.py           7-language registry + directive
├── scripts/                   smoke_test, smoke_tools, smoke_test_vision,
│                              smoke_test_bbox, smoke_test_cities
├── static/
│   └── index.html             single-file React + Leaflet + SVG bbox overlay
├── Dockerfile                 HF Spaces ready
├── requirements.txt
├── README.md                  HF Spaces frontmatter
└── .env (gitignored)          OPENROUTER_API_KEY, GOOGLE_MAPS_API_KEY,
                               MAPBOX_ACCESS_TOKEN

README.md                      GitHub landing page
DEPLOY.md                      step-by-step HF Space deploy
STATUS.md                      this file
SKILL.md                       Claude Code skill (project rules)
FLOODIQ_BACKEND_SPEC.md        original 1086-line build spec
```

### Frontend layout

The React app lives entirely in `backend/static/index.html`
(`<script type="text/babel">`) — no build step. Three screens:

- **SearchScreen** — address input, language picker, example chips
- **AgentsScreen** — Leaflet map of geocoded address, 9 agent rows
  with live SSE status (idle / queued / working / done / error),
  500m radius circle
- **DossierScreen** — sections numbered at render time based on
  which conditional blocks are present:
  - **§01 Start here — what to do this month** (action plan, default open)
  - **§02 Insurance options, in plain English** (verified products, default open)
  - **§03 What we saw at the property** (Street View + Satellite tabs,
    SVG bounding-box overlay) — *renders when either vision agent
    has data*
  - **§04 Why FEMA's flood map isn't the whole story** (multimodal-
    reasoning callout, development-pressure callout when permits exist,
    full reasoning trace toggle, default closed)
  - **§05 Wider neighborhood — beyond just flooding** (FEMA NRI
    multi-hazard) — *renders when NRI lookup succeeds (any US address)*
  - **§06 The raw signals we looked at** (default closed)
  - **§07 Recent local flood news**

---

## Versions shipped (v0.7 → v0.14.1)

| Version | Highlight |
|---|---|
| **v0.7** | Multi-language dossier (7 langs); single-Space deploy; Census Geocoder fallback; verified insurance catalog |
| **v0.8** | Bounding-box detection on Street View (SVG overlay) |
| **v0.9** | Multimodal risk analyst — image + reasoning + 6 data sources in one call |
| **v0.10** | 3-image multimodal (satellite + topo + street view) |
| **v0.11** | Dedicated satellite agent with bbox detection (dropped topo — Mapbox outdoors doesn't show contours in cities) |
| **v0.12** | Building permits as flood-risk leading indicator (Chicago) |
| **v0.13** | Tier-1 multi-city: Chicago + NYC + SF + LA + Austin |
| **v0.14** | Regional risk agent — FEMA NRI multi-hazard at county level (all US counties) |
| **v0.14.1** | System-prompt tuning for the 4-layer signal hierarchy (Property / Neighborhood / Visual / Regional) |

---

## Spec bugs caught and fixed

Useful for the writeup ("what we learned implementing the spec / live data"):

| Bug | Fix |
|-----|-----|
| `extract_reasoning` read `r.get("content")` | Real key is `text`; also fall back to top-level `reasoning` string |
| FEMA layer 28 `outFields=VERSION_ID` → ArcGIS HTTP 200 with error body that silently looked like UNMAPPED | Drop VERSION_ID; surface `SFHA_TF`/`DEPTH`/`STUDY_TYP`; detect ArcGIS error envelope |
| Spec gave wrong Chicago DWM phone (312-747-7030) | Real number is 311 or 312-744-7000 (verified via web) |
| NFIP "Preferred Risk Policy" — Gemma's training data | Retired Oct 2021 with Risk Rating 2.0; catalog now uses generic "NFIP flood insurance" with floodsmart.gov link |
| Nominatim doesn't have many US residential addresses | US Census Geocoder fallback (TIGER/Line, returns county FIPS too) |
| NOAA NWS 301-redirects high-precision lat/lon | `follow_redirects=True` |
| GDELT 1/5s per-IP rate limit silently 429s second of two parallel calls | asyncio lock + 5.5s gap + 429 retry-once |
| OpenRouter 502 Bad Gateway killed agents permanently | Retry 5xx with same backoff as 429 |
| HF Spaces secrets UI adds trailing `\n` to keys → httpx "illegal header value" | `.strip()` at config load time |
| Per-city Socrata schemas: NYC has no `suffix`, no `_total_sqft`; LA stores lat/lon as text; SF stores cost as text | Per-city config in `cities.py`; PostgreSQL `::number` cast for text-stored numerics |
| NRI's `_RISKR` is the rating string, `_RISKS` is the score — opposite of how the schema aliases read | Trust the data over the schema; documented in `nri_county.py` |
| FEMA NRI behind a click-through download (no public REST API) | Found exposed FeatureServer behind FEMA's RAPT app; queryable by point with no auth |

---

## Known limitations

### What works but is scoped down
- **Local 311 + permits = 5 cities** (Chicago, NYC, SF, LA, Austin).
  Each new city = one registry entry plus per-city flood-category mapping.
  NRI multi-hazard works for all US counties; only the city-specific
  signals are gated to the 5.
- **Insurance catalog is hand-curated and small.** ~6 products
  (sewer rider, NFIP, private flood, parametric, plus city-specific
  resources). Real products only — coverage is thin but pricing is honest.
- **Map is Leaflet + OSM/CARTO basemap.** No FEMA flood-zone polygon
  overlay; it's accessible via NFHL WMS but adds another dependency.

### What wobbles
- **GDELT** sometimes 429s aggressively despite the rate-limit lock —
  cross-process IP cool-down can stretch beyond our 5.5s gap. Empty
  news/archive states render gracefully.
- **OpenRouter free tier** rate-limits without BYOK. Required for
  reliable runs (see Local dev → BYOK).
- **USGS streamflow** sometimes returns a stale 2010-vintage reading
  alongside current gage height; risk agent generally picks the right
  one but it's noisy.
- **HF Spaces free tier** sleeps containers after ~48h of inactivity.
  First wake takes ~10s. Tolerable for the demo.

### Deliberately out of scope
- **No Vite / React build pipeline.** Single-file `index.html` deploys
  with no toolchain.
- **No database.** Everything per-request; no caching; no PII stored.
- **No follow-up conversation.** The dossier is one-shot. Multi-turn
  function-calling chat is on the roadmap.
- **No NOAA Storm Events DB.** No clean public JSON API. We use
  GDELT 24-month news as a proxy, documented in `archive_agent.py`.
- **No real elevation contours.** Tried Mapbox outdoors + USGS Topo;
  neither renders contours in dense urban or flat-metro areas. The
  satellite agent's catchment analysis fills the gap.
- **Boston, Houston, Miami, Dallas, Seattle.** Each has working
  open-data portals but on different platforms (CKAN, custom REST,
  inconsistent flood categories). Documented as future work.

---

## What's left before submission

In priority order:

1. **Kaggle Writeup** (≤1,500 words, Global Resilience track). Lead
   with the FEMA-gap insight, then layered multimodal architecture,
   then verified-catalog approach, then multi-city + multi-hazard,
   then the wider playbook.
2. **YouTube demo video** (≤3 min, storytelling-first per Kaggle rules).
   Suggested arc: hook → walk through one assessment live (Chicago
   for FEMA-gap drama OR Houston for multi-hazard demo) → reasoning
   trace zoom-in → action plan → repo + URL outro.

That's it. Everything else (deploy, README, multi-city, multi-hazard,
multimodal vision, bbox detection) is shipped.

### Hackathon alignment checklist

```
[x] Uses Gemma 4 as the only LLM (OpenRouter free tier + BYOK)
[x] Native function calling (smoke-tested; agents use it)
[x] Reasoning mode (risk_agent, trace surfaced in UI with layer-citation)
[x] Native multimodal vision (Street View + satellite, both with bbox)
[x] Native bounding-box detection (yxyx normalized 0-1000 — verified)
[x] Interleaved multimodal reasoning (2 images + 7 data in one call)
[x] Long context (256K — comfortably handles the bundled prompt)
[x] 140+ language support (7 languages live, prompt directive)
[x] Multi-hazard awareness (NRI: wildfire, hurricane, tornado, etc.)
[x] Agentic workflows (9 agents, parallel-then-sequential, SSE)
[x] Real-world problem (flood-risk communication gap, well-documented)
[x] Free public data sources only (FEMA NFHL+NRI, USGS, NOAA, GDELT,
    Open-Meteo, OSM, 5 city open-data portals)
[x] Live demo: kredd25-flutiq.hf.space
[x] Public GitHub repo: github.com/kredd2506/Gemma4Good_FlutIQ
[ ] YouTube video (≤3 min)
[ ] Kaggle Writeup (≤1,500 words)
```

---

## Local dev quick reference

Single uvicorn serves both API and bundled frontend.

```bash
cd backend
python3.13 -m venv .venv
.venv/bin/pip install -r requirements.txt
cat > .env <<'EOF'
OPENROUTER_API_KEY=sk-or-v1-...   # required (BYOK below)
GOOGLE_MAPS_API_KEY=AIzaSy...     # optional — Street View tab
MAPBOX_ACCESS_TOKEN=pk.eyJ1...    # optional — Satellite tab
EOF
set -a && source .env && set +a
.venv/bin/uvicorn app.main:app --reload --port 8000
# visit http://127.0.0.1:8000
```

Smoke tests:

```bash
PYTHONPATH=. .venv/bin/python scripts/smoke_test.py            # Gemma 4 sanity
PYTHONPATH=. .venv/bin/python scripts/smoke_tools.py           # data tools
PYTHONPATH=. .venv/bin/python scripts/smoke_test_vision.py     # multimodal
PYTHONPATH=. .venv/bin/python scripts/smoke_test_bbox.py       # bbox detection
PYTHONPATH=. .venv/bin/python scripts/smoke_test_cities.py     # 5-city e2e
```

For deploy → HF Spaces, see [DEPLOY.md](DEPLOY.md).

### Required: BYOK for OpenRouter

The default `:free` tier is a shared upstream pool that 429s after
~2 calls. For a 9-agent system that means assessments fail constantly.

1. Get a free Google AI Studio key at [aistudio.google.com/apikey](https://aistudio.google.com/apikey)
2. Paste it into [openrouter.ai/settings/integrations](https://openrouter.ai/settings/integrations)
3. The same `:free` model IDs now route through *your personal*
   Google AI Studio quota (15 RPM / ~1500 RPD per integration).
   OpenRouter still bills $0.

---

## Recent commit log

```
a0a8697  README: refresh from v0.7 → v0.14.1
a201ec0  v0.14.1: tune three system prompts for layered signals
d4bd648  v0.14: regional_risk_agent — FEMA NRI multi-hazard
5b1d9dd  v0.13: Tier-1 multi-city (Chicago + NYC + SF + LA + Austin)
aa9a611  v0.12: building permits as flood-risk leading indicator
979a1cd  v0.11: dedicated satellite-analysis agent with bbox
157ea5e  v0.10: 3-image multimodal (deprecated topo)
2950324  v0.9: multimodal risk analyst — vision + reasoning + 6 data sources
123b79a  v0.8: Gemma 4 bounding-box detection on Street View
755f59e  v0.7: README rewrite + version bump for multi-language + vision
8d610e5  feature: streetview agent — multimodal Gemma 4 vision
0a241a3  advisor: stop inventing insurance products — verified catalog
3883936  geocoder: US Census fallback for residential addresses
20394dc  frontend: wire index.html prototype to live backend SSE
0a8dc60  backend: full 7-agent pipeline working end-to-end
1448313  backend: vertical slice — geocoder + FEMA agent + SSE end-to-end
e7c26f4  Initial commit: FlutIQ frontend prototype + backend spec + Claude skill
```

(Full log: `git log --oneline`)
