# FlutIQ — current state (2026-05-02)

A snapshot of what's built, what works, what wobbles, and what's left.
This is a working doc, not a polished README — that comes later as a
hackathon deliverable.

---

## What FlutIQ is

A multi-agent flood-risk advisor for the **Gemma 4 Good Hackathon**
(Kaggle, deadline May 18, 2026, Global Resilience track).

Mission: **reduce the complexity and scariness of insurance**, not just
compute a flood risk score. The technical pitch (FEMA-gap, multi-agent,
Gemma 4 reasoning) is the vehicle; the goal is making a homeowner feel
less overwhelmed about flood-insurance decisions.

User flow: enter a US address → 7 specialist Gemma 4 agents investigate
in parallel against free public data → user gets a personalized dossier
with verified insurance options, a prioritized action plan, and a
plain-English explanation of *why FEMA's flood map isn't the whole
story*.

Live at: not deployed yet (local only). Repo:
[github.com/kredd2506/Gemma4Good_FlutIQ](https://github.com/kredd2506/Gemma4Good_FlutIQ).

---

## What's working end-to-end

Run an assessment locally, see structured live results in a browser:

```
POST /api/assess  →  geocode  →  5 data agents in parallel  →
                     risk-analyst (Gemma 4 reasoning mode)  →
                     advisor (catalog-driven)  →
                     compiled dossier
```

All seven agents return structured JSON, streamed via Server-Sent
Events to a React frontend that renders a live dossier with a real
Leaflet map and an expandable "Gemma 4 reasoning trace" panel.

Verified passing flows:
- **Houston Allen Pkwy** (FEMA Zone AE, SFHA) → dossier explains
  insurance is required, mitigation tips
- **4521 S Drexel Blvd, Chicago** (FEMA Zone X) → dossier surfaces the
  FEMA-gap warning that combined-sewer urban flooding is the real
  risk in Chicago, recommends sewer endorsement first
- **1133 Potomac Rd, Atlanta** (FEMA Zone X) → same gap framing,
  generic nationwide resources (no Chicago leak)

Typical assessment time: ~30–45s end-to-end (limited by Gemma 4
inference + the GDELT 5-second rate-limit pacing).

---

## Architecture

```
React (index.html, Babel-standalone, ~1200 lines)
  │
  └─ POST /api/assess   ──── SSE ────►   FastAPI / uvicorn (Python 3.13)
                                          │
                                          ▼
                                 Geocoder
                                 (Nominatim → Census fallback)
                                          │
                                          ▼
                          Orchestrator (asyncio.gather)
                          ┌───────┬────────┬───────┬────────┬─────────┐
                          ▼       ▼        ▼       ▼        ▼         ▼
                        FEMA    Local    Weather  News   Archive
                       (NFHL)  (311)    (USGS+   (GDELT (GDELT
                                          NOAA+   6mo)   24mo)
                                       Open-Meteo)
                          │
                          ▼ (after all 5 done)
                     Risk analyst  (Gemma 4 reasoning=on)
                          │
                          ▼
                       Advisor  (catalog-driven, no inventing)
                          │
                          ▼
                     dossier JSON
```

### Files & purpose

```
backend/
├── app/
│   ├── main.py                FastAPI + CORS
│   ├── config.py              env + model IDs + URLs
│   ├── api/
│   │   ├── health.py          GET /api/health
│   │   └── assess.py          POST /api/assess (SSE)
│   ├── agents/
│   │   ├── orchestrator.py    parallel-then-sequential agent runner
│   │   ├── fema_agent.py      Gemma interprets FEMA NFHL response
│   │   ├── local_agent.py     Chicago-only 311 (graceful elsewhere)
│   │   ├── weather_agent.py   USGS + NOAA + Open-Meteo, fan-out
│   │   ├── news_agent.py      GDELT 6-month flood news
│   │   ├── archive_agent.py   GDELT 24-month as Storm Events proxy
│   │   ├── risk_agent.py      THE Gemma 4 reasoning showcase
│   │   └── advisor_agent.py   catalog-driven, no invented products
│   ├── tools/
│   │   ├── geocoder.py        Nominatim → US Census fallback
│   │   ├── fema.py            FEMA NFHL ArcGIS REST (layer 28)
│   │   ├── chicago_311.py     Socrata SODA (WIB/SFL codes)
│   │   ├── usgs.py            stream gauge + current readings
│   │   ├── noaa.py            point forecast + active flood alerts
│   │   ├── open_meteo.py      flood + precipitation forecast
│   │   └── gdelt.py           DOC API + per-IP rate-limit lock
│   ├── llm/
│   │   ├── client.py          OpenRouter wrapper, 429+5xx retries
│   │   └── prompts.py         system prompts per agent
│   └── data/
│       └── insurance_catalog.py  CURATED real products + resources
├── scripts/
│   ├── smoke_test.py          basic + reasoning + tools, 3-way
│   ├── smoke_test_tools.py    tool-call only, isolated
│   └── smoke_tools.py         exercise each data tool end-to-end
├── Dockerfile                 HF Spaces ready
├── requirements.txt
├── README.md                  HF Spaces frontmatter
└── .env (gitignored)          OPENROUTER_API_KEY

index.html                     single-file React+Leaflet frontend
SKILL.md                       Claude Code skill, project rules
FLOODIQ_BACKEND_SPEC.md        original 1086-line build spec
flutiq-skill.tar               packaged skill bundle
```

### Frontend layout

The React app lives entirely in `index.html` (`<script type="text/babel">`)
to keep the deploy story trivial — no build step. Three screens:

- `SearchScreen` — address input + example chips
- `AgentsScreen` — Leaflet map of geocoded address, agent list with live
  status from SSE, 500m radius circle
- `DossierScreen` — five sections, ordered for the mission:
  - **§01 Start here — what to do this month** (action plan, default open)
  - **§02 Insurance options, in plain English** (verified products, default open)
  - **§03 Why FEMA's flood map isn't the whole story** (default closed)
  - **§04 The raw signals we looked at** (default closed)
  - **§05 Recent local flood news**

---

## Spec bugs caught and fixed during build

Worth keeping a list — these are useful for the writeup ("what we
learned implementing the spec"):

| Bug | Fix |
|-----|-----|
| `extract_reasoning` read `r.get("content")` | Real key is `text`; also fall back to top-level `reasoning` string |
| FEMA layer 28 `outFields=VERSION_ID` → ArcGIS HTTP 200 with `{"error":...}` body that silently looked like UNMAPPED | Drop VERSION_ID, also surface `SFHA_TF` / `DEPTH` / `STUDY_TYP`; detect ArcGIS error envelope |
| Spec gave wrong Chicago DWM phone (312-747-7030) | Real number is 311 or 312-744-7000 (verified via web) |
| NFIP "Preferred Risk Policy" — Gemma's training data | Retired Oct 2021 with Risk Rating 2.0; catalog now uses generic "NFIP flood insurance" with floodsmart.gov quote link |
| Nominatim doesn't have many US residential addresses | US Census Geocoder fallback (TIGER/Line, returns county FIPS too) |
| NOAA NWS 301-redirects high-precision lat/lon | `follow_redirects=True` |
| GDELT 1/5s per-IP rate limit silently 429s second of two parallel calls | asyncio lock + 5.5s gap + 429 retry-once |
| OpenRouter 502 Bad Gateway killed agents permanently | Retry 5xx with same backoff as 429 |

---

## Known limitations

### Things that work but are scoped down
- **Local 311 agent is Chicago-only.** Other cities show "—" with an
  honest "no 311 dataset wired for this city" note. Adding NYC, Houston,
  Atlanta, etc. would be a per-city tool implementation.
- **Insurance catalog is hand-curated and small.** 4 products
  (sewer rider, NFIP, private flood, parametric). Real products only
  but coverage is thin. Pricing is "typical range" not live quotes.
- **Map is Leaflet + OSM/CARTO basemap.** No flood-zone overlay yet
  (FEMA NFHL has WMS tiles we could add as a polygon layer).

### Things that wobble
- **GDELT** for non-Chicago / non-major US cities sometimes returns
  empty even with the rate-limit fix. Architecture handles it gracefully
  (empty news state, not a crash).
- **OpenRouter free tier** rate-limits. BYOK to a Google AI Studio key
  in OpenRouter integrations is required for reliable demo runs.
  Without BYOK: ~2 assessments before 429s.
- **USGS streamflow value field** sometimes returns a 2010-vintage
  reading alongside the current gage height. Risk agent generally
  picks the right one but it's noisy.

### Things deliberately not done
- No Vite/React build pipeline. The single-file index.html works for
  a hackathon and deploys with no build step.
- No database. Everything per-request, no caching, no PII stored
  (per spec).
- No archive_agent for NOAA Storm Events DB — that has no clean public
  JSON API. We use GDELT 24-month as a proxy, documented in the agent
  source.
- No real flood-zone polygon overlay on the map.

---

## What's left before submission

Roughly in priority order. Nothing here is blocked on anyone but us.

1. **Deploy** — backend to HF Spaces (Docker SDK, OPENROUTER_API_KEY
   in secrets), frontend `index.html` to Cloudflare Pages with
   `?api=https://kredd2506-flutiq.hf.space` query param. Estimated
   time: ~30 min.
2. **README rewrite** — public-facing, replaces the HF Spaces
   frontmatter file in `backend/README.md` and adds a top-level
   `README.md` for the GitHub landing page. Cover: what it does, how
   to run locally, the architecture diagram, the FEMA-gap thesis,
   credits.
3. **Dossier polish** — open items from feedback:
   - "FlutIQ" wordmark vs "FlutIQ" (rest of project) — pick one and
     make it consistent
   - Map legend still says "311 reports" generically; could remove
     for non-Chicago
   - The synthetic placeholder map (shown briefly during geocoding)
     could just be a spinner
4. **YouTube demo video** (≤3 min, storytelling-first per Kaggle rules).
   Suggested arc: hook (FEMA missed Chicago basement floods) → walk
   through one assessment live → reasoning trace zoom-in → action plan
   on screen → repo + URL outro.
5. **Kaggle Writeup** (≤1,500 words, Global Resilience track). Lead
   with the FEMA-gap insight, then the 7-agent design, then Gemma 4
   reasoning showcase, then real-world resources (verified catalog,
   not invented products), then the wider playbook (other cities).

### Hackathon alignment checklist

```
[x] Uses Gemma 4 as the only LLM (OpenRouter free tier)
[x] Demonstrates native function calling (smoke-tested, agents use it)
[x] Demonstrates reasoning mode (risk_agent, trace surfaced in UI)
[x] Demonstrates agentic workflows (7 agents, orchestrator pattern)
[x] Solves a real-world problem (flood-risk communication gap)
[x] Free public data sources only (FEMA, NOAA, USGS, 311, GDELT, OSM)
[x] Multi-agent architecture clearly documented
[x] Public GitHub repo (just pushed: github.com/kredd2506/Gemma4Good_FlutIQ)
[ ] Live demo (publicly accessible, no login) — pending deploy
[ ] YouTube video (≤3 min)
[ ] Kaggle Writeup (≤1,500 words)
```

---

## Local dev quick reference

```bash
# Backend
cd backend
python3.13 -m venv .venv
.venv/bin/pip install -r requirements.txt
# put OPENROUTER_API_KEY=sk-or-v1-... in backend/.env (gitignored)
set -a && source .env && set +a
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000

# Frontend (separate terminal)
cd ..
python3 -m http.server 5173 --bind 127.0.0.1
# visit http://127.0.0.1:5173

# Smoke tests
cd backend
PYTHONPATH=. .venv/bin/python scripts/smoke_test.py     # Gemma 4 sanity
PYTHONPATH=. .venv/bin/python scripts/smoke_tools.py    # data tools
```

### Required: BYOK for OpenRouter

The default `:free` tier is a shared upstream pool that 429s after
~2 calls. Required for any reliable run:

1. Get a free Google AI Studio key at [aistudio.google.com/apikey](https://aistudio.google.com/apikey)
2. Paste it into [openrouter.ai/settings/integrations](https://openrouter.ai/settings/integrations)
3. The same `:free` model IDs now use *your personal* Google AI Studio
   quota (15 RPM / ~1500 RPD per integration)

---

## Commits so far

```
d05366f  llm/client: retry transient 5xx upstream errors
0a241a3  advisor: stop inventing insurance products — drive from a verified catalog
03b740a  frontend: kill Chicago-only leftovers from prototype
3883936  geocoder: add US Census fallback when Nominatim returns nothing
20394dc  frontend: wire index.html prototype to live backend SSE
0a8dc60  backend: full 7-agent pipeline working end-to-end
1448313  backend: vertical slice — geocoder + FEMA agent + SSE end-to-end
e7c26f4  Initial commit: FlutIQ frontend prototype + backend spec + Claude skill
```
