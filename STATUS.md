# FlutIQ — current state (2026-05-14, v0.15.4)

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

## Versions shipped (v0.7 → v0.15.4)

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
| **v0.15** | Dual-mode (FlutIQ Cloud via OpenRouter + FlutIQ Edge via Ollama / Gemma 4 e4b on-device) + expert-briefing dossier reframe (`plain_verdict`, `before_you_move_in[]` with citations, mitigation_actions bucketed into drainage / infiltration / barrier, synthesis-receipt strip) |
| **v0.15.1** | Synthesis-receipt field-name bug — was reading wrong key for building permits; permits row now reliably surfaces in the receipt strip |
| **v0.15.2** | Commercial property detection — geocoder classifies Nominatim hits residential/commercial; advisor early-returns for commercial; dossier hides homeowner-only sections + shows an amber banner. Chips re-curated to drop any commercial buildings (Empire State Bldg, LAX admin) |
| **v0.15.3** | Non-English dossiers were patchy on two distinct axes: (a) Tier-1 BUG — Gemma 4 translated enum values like `product_id` and `bucket`, the strict post-parse filter silently dropped every recommendation, insurance + actions came back empty; (b) UI chrome (risk-tag, headline, section titles, banners) was hardcoded English with no translation path. Fix: strengthened language directive + advisor prompt to lock enum values to English; new `UI_STRINGS` dict in `index.html` covers ~27 keys × 7 languages with a `tr(lang, key)` helper threaded through `mapDossier` and `DossierScreen` |
| **v0.15.4** | After v0.15.3, end-to-end testing of all 7 languages live against the HF Space caught one remaining gap: `risk_agent.plain_verdict` rendered empty for `zh` + `ar` (the two non-Latin scripts). The field's instruction had "Second person, plain English, ~10th-grade reading level" — "plain English" contradicted the language directive on non-Latin output. Fix: rewrite the field as REQUIRED + explicit "write the VALUE in the user's chosen language", reorder it to position 3 in the JSON schema for token-budget safety, and extend the explicit language-target reminder to all other string-valued risk fields. All 7 languages now verified end-to-end. |

---

## v0.15.4 — what shipped this round

End-to-end live testing of all 7 dossier languages exposed one final
language-related bug. Five rounds in, the non-English code path is
now genuinely verified, not just "the prompt directive is wired."

**The hunt:**
- Ran `flutiq_lang_test.py` against the deployed Space — POST
  `/api/assess` with the same Chicago address (`4521 S Drexel Blvd`)
  and `language` ∈ {en, es, zh, vi, ht, ar, tl}, then parsed the
  final `complete` SSE event's dossier payload.
- For each language we checked: insurance count, mitigation count,
  before_you_move_in count, `advisor.tldr` quality, `risk.plain_verdict`
  quality. Total ~9 LLM calls × 7 languages ≈ 63 calls, serialized
  to stay under upstream BYOK rate limits.
- Tier-1 fix (v0.15.3) confirmed working for **all 7**: every
  language returned 2 insurance recommendations with the correct
  English `product_id`s (`homeowners_sewer_rider`, `nfip_standard`)
  and 3 mitigation actions across all three buckets (`barrier`,
  `drainage`, `infiltration`).
- `advisor.tldr` rendered fluent target-language prose in all 7,
  including the lower-resource Haitian Creole and Tagalog (the
  latter with appropriate English code-switching, which is natural
  in Filipino usage).

**The bug:**
- `risk.plain_verdict` came back EMPTY for `zh` and `ar` — and ONLY
  those two. Every other risk-agent field (`risk_score`, `risk_level`,
  `fema_gap_explanation`, etc.) populated normally. The pattern
  cleanly localized to non-Latin-script languages.
- Root cause: the field instruction said "Second person, plain English,
  ~10th-grade reading level" — when the system-prompt language
  directive says "write in Mandarin / Arabic", the model received
  contradictory signals about what language to use for THIS specific
  field. Latin-script languages somehow tolerated the conflict
  (Spanish + Vietnamese + Haitian Creole + Tagalog all populated);
  non-Latin scripts didn't.

**Fix in `risk_agent.py`:**
- Drop "plain English" from the `plain_verdict` instruction. Replace
  with explicit "Write the VALUE in the user's chosen output language
  (per the language directive in the system prompt) — do NOT default
  to English if another language was requested. The JSON key
  'plain_verdict' itself stays English."
- Mark the field `REQUIRED, NEVER EMPTY`; add a closing reminder at
  the bottom of the prompt: "Generate `plain_verdict` early in the
  JSON object (it is the most prominent field on the dossier)."
- Reorder the JSON schema so `plain_verdict` is field 3 (right after
  `risk_score` and `risk_level`). Token-budget safety: reasoning
  mode produces a long CoT trace; if the trailing JSON ever truncates,
  the user still gets the headline verdict.
- Extend the "value in user's chosen language" reminder to
  `fema_gap_explanation`, `visual_corroboration`, `key_risk_factors`,
  `mitigating_factors`, `summary` — same class of risk, fix once.

**Verification:**
- Re-tested `zh` and `ar` against the same address after deploy.
  `plain_verdict` came back at 171 chars (zh) and 336 chars (ar),
  both fluent and substantive (mentioned FEMA Zone X, the
  densification leading indicator, and the 26%/21% 30-year cumulative
  probability). `fema_gap_explanation` and `visual_corroboration`
  also now fluent in the target languages.

---

## v0.15.3 — what shipped this round

Hand-testing the Spanish dossier on the Chicago Drexel address
surfaced two distinct failures the original "translate everything"
prompt directive caused.

**Tier-1 bug — empty advisor sections:**
- Gemma 4 in Spanish mode helpfully translated the technical enum
  values inside the JSON it returned: `"nfip_standard"` became
  `"nfip_estandar"`, bucket `"drainage"` became `"drenaje"`. The
  strict post-parse filter in `advisor_agent.py` then silently
  dropped every `insurance_recommendations` entry (none matched a
  catalog `product_id`), and the bucket-grouped renderer collapsed
  every `mitigation_actions` entry into the "other" bucket (or the
  model emitted an empty array — same observable outcome).
- The dossier rendered with "The advisor agent did not return
  insurance recommendations for this address" and only the
  forced-passthrough city resources in the action plan. Functionally
  broken Spanish.

**Tier-1 fix — strict enum preservation:**
- `languages.py` directive now explicitly enumerates the enum /
  identifier values that must NOT be translated (`product_id`,
  `bucket`, `cite`, `priority`, `effort`, `impact`) with concrete
  examples, AND explains *why* (silent parser drops).
- `advisor_agent.py` repeats the same enum list in the CRITICAL block
  at the bottom of the user prompt — adjacent to the catalog, so
  the constraint is in context when the model is actually generating
  the IDs.

**Tier-2 polish — frontend i18n:**
- Until this round, only model-generated prose was translated; the
  React JSX chrome (risk-tag, bold headline, every section title,
  Bottom-Line / Synthesized-From / Commercial banner labels) was
  hardcoded English. Read jarringly mixed-language for Spanish.
- New `UI_STRINGS` dict at the top of `index.html` covers ~27 keys
  × 7 languages: risk-level labels (3), risk headlines (10 across
  6 cases), section titles (8), bottom-line + receipt labels (3),
  commercial banner label + sub + body (3).
- New `tr(lang, key)` helper with English fallback. `mapDossier`
  now takes `lang` and emits translated headline templates;
  `DossierScreen` now takes `language` prop and builds a
  closure-bound `t(key)` for chrome translations; `App` passes
  the active picker language through.
- Translations: Spanish hand-written carefully. The other six
  (Mandarin, Vietnamese, Haitian Creole, Arabic, Tagalog) written
  to the best of multilingual capability — should be reviewed by
  native speakers before production, but ship-ready for hackathon
  submission.

**Intentionally NOT in this round:**
- Methodology footer, disclaimer, severity chips on indicators
  (`moderate`, `low`, `high`), the "FEMA may understate risk" badge,
  visual-risk readouts (`VISUAL RISK`, `AT GRADE`, `CONFIDENCE`),
  toolbar (`DOSSIER · DATE · v1`). All still English. Documented
  as a known scoped-down item; can land in a follow-up pass.

---

## v0.15.2 — what shipped this round

**Commercial property detection:**
- A user clicked the LA chip and got residential-flavored insurance
  advice for the **Clifton A. Moore Administration Building at LAX** —
  the building has a name, it's clearly commercial, and FlutIQ was
  still producing a "For this property…" homeowner insurance pitch
  and an action plan. Root cause: property type wasn't surfaced
  anywhere; advisor was hardcoded residential.
- Fix went with the on-brand path (FlutIQ's mission is homeowners,
  not commercial coverage):
  - `geocoder.py` now classifies Nominatim hits as `residential` or
    `commercial` using `class` / `type` / `name` heuristics. Defaults
    to residential unless the signal is confident (osm `class` ∈
    {amenity, tourism, shop, office, industrial, …}, `type` in a
    closed institutional set, or `class=building` with a real `name`).
    Census fallback assumes residential (TIGER street addresses).
  - `advisor_agent.py` short-circuits for commercial — skips the
    Gemma 4 call entirely and returns a graceful note pointing the
    user to a commercial insurance broker.
  - `index.html` reads `property_type` from the dossier, renders an
    amber **"Commercial property"** banner near the top, and
    suppresses the Before-you-sign / Actions / Insurance sections.
    Dynamic section numbering adjusts; the FEMA-gap, NRI, vision,
    and signals sections still render because the building still
    floods.
- Verified live against real Nominatim API:
  `1 World Way` (LAX) → commercial · `350 5th Ave` (Empire State Bldg)
  → commercial · `4521 S Drexel Blvd`, `Echo Park`, `Greenwich Village`,
  `Houston Heights` → residential.

**Example chips re-curated:**
- Initial chip pick included LAX (1 World Way) and the Empire State
  Building (350 5th Ave) — both correctly flagged by the new
  classifier as commercial, both defeating their chips' demo purpose
  of showing the full pipeline. Swapped to neighborhood-level
  residential anchors that still resolve to the Tier-1 city for
  full 311 + permits coverage:
  - **Chicago** — 4521 S Drexel Blvd (full Tier-1 + FEMA-gap drama)
  - **NYC** — Greenwich Village (full Tier-1 + CSO/sewer story)
  - **LA** — Echo Park (full Tier-1 + NRI wildfire + earthquake VH)
  - **Houston** — Houston Heights (outside Tier-1, NRI hurricane)

---

## v0.15.1 — quick fix

The synthesis-receipt strip (`Synthesized from …`) was reading
`D.local?.permits` for the permits row. The actual advisor-output
shape nested permits under `D.local?.construction.permits_count` /
`construction.total_reported_cost`. Result: the strip always rendered
without the permits row even on Chicago test addresses with 89
permits and $190M in reported costs. One-character fix landed same
day; permits row now reliably appears on densification-pressure
addresses.

---

## v0.15 — what shipped this round

**Dual-mode (Cloud + Edge):**
- New `INFERENCE_BACKEND` env var in `config.py` switches the LLM
  endpoint without touching agent code. `"openrouter"` (default,
  used by the HF Space) → cloud Gemma 4 31B. `"ollama"` → local
  `gemma4:e4b` at `localhost:11434/v1`.
- `client.py` now reads `LLM_BASE_URL` / `LLM_API_KEY` /
  `MODEL_PRIMARY` from config; OpenRouter-only telemetry headers
  (`HTTP-Referer`, `X-Title`) only sent in cloud mode; httpx timeout
  bumped to 300s in Ollama mode (laptop is slower than OpenRouter).
- `main.py` now serves index.html via `HTMLResponse` with
  `__INFERENCE_BACKEND__` placeholder substitution, so the page
  knows its variant before any JS runs.
- Frontend re-skins itself based on `data-variant`: blue accents +
  "FlutIQ Cloud" wordmark for cloud, green accents + "FlutIQ Edge"
  for ollama. Same React app, ~25 lines of CSS overrides.
- Verified end-to-end on `gemma4:e4b` against an M4 Pro 24 GB:
  `/api/assess` for a Chicago address completes in ~190 s, all 9
  agents finish, both vision agents (satellite + streetview) produce
  grounded findings.
- Hackathon-brief surface: addresses "local frontier intelligence",
  "privacy is non-negotiable", "E2B and E4B for edge".

**Expert-briefing dossier reframe:**
- `RISK_AGENT_SYSTEM_PROMPT` reframed: "you are producing an expert
  briefing for someone about to live/buy/rent here … they would
  otherwise spend several weeks and hundreds of dollars piecing
  this together themselves. Your value is synthesis and time, not
  novel prediction." Voice on the new `plain_verdict` field is
  second-person, ~10th-grade reading, lead with the bottom line
  then the single most important reason then the trend direction.
- `risk_agent` schema gains `plain_verdict` (validated live: produces
  3-5 sentence verdicts that pass smell test on Chicago test address).
- `advisor_agent` schema gains `before_you_move_in[]` (each item:
  `check`, `why`, `how`, `cite` — the citation tag must come from a
  closed enum: FEMA / 311 / Permits / City sewer / Satellite /
  Street view / NRI / USGS+NOAA).
- `advisor_agent` `mitigation_actions[]` gains a `bucket` field
  (`drainage` | `infiltration` | `barrier`); the prompt enumerates
  rainwater harvesting, permeable pavers, groundwater recharge,
  backwater valve, sump-pump-with-battery as part of the action
  vocabulary so the model reliably covers all three buckets.
- Frontend dossier rewrite: Bottom-line verdict card + "Synthesized
  from …" receipt strip + Before-you-sign Section above the existing
  actions/insurance sections; dynamic section numbering reshuffles
  cleanly when the new before-you-sign Section is present.

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
- **Residential properties only** for insurance + homeowner-action
  advice (v0.15.2). Commercial addresses still get the FEMA / NRI /
  vision / signals analysis but the dossier suppresses the action
  plan, insurance, and before-you-sign sections with an honest
  banner pointing the user to a commercial broker. Catalog is
  homeowner-focused on purpose.
- **Partial UI translation** (v0.15.3 / v0.15.4). Body prose
  (bottom-line verdict, NRI narrative, vision findings, action
  descriptions, advisor TLDR), risk-tag, hero headline, all 8
  section titles, and the commercial banner are translated across
  all 7 languages. **Not yet translated**: methodology footer,
  disclaimer, severity chips on indicators ("moderate" / "low" /
  "high"), the "FEMA may understate risk" badge, visual-risk
  readouts ("VISUAL RISK", "AT GRADE", "CONFIDENCE"), the toolbar
  ("DOSSIER · DATE · v1"). Documented as a follow-up; non-English
  translations should also be reviewed by native speakers before
  any production deploy.
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
[x] 140+ language support (7 languages live, verified end-to-end
    against the deployed Space — all populate insurance, actions,
    and a fluent bottom-line verdict in the target language)
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
a05c28d  docs: add FlutIQ Edge setup section to README
a5e8d7a  frontend: FlutIQ Edge callout + dark mode now the default
234c667  frontend: rebuild "How it works" from FlutIQ_HowItWorks_Rewrite.md spec
48f7b4a  frontend: restructure "How it works" — Question / Investigate / Decide
6ef386c  frontend: refresh stale "How it works" + methodology copy + bump badge
677607c  docs: refresh README + STATUS for v0.15.3 + v0.15.4
147b9e6  v0.15.4: risk_agent plain_verdict empty for zh + ar — language fix
0565e0d  v0.15.3: make non-English dossiers actually work end-to-end
c874de0  docs: refresh README + STATUS for v0.15.1 + v0.15.2
375b426  v0.15.2: detect commercial properties, skip homeowner advice
ebdb8cb  frontend: rotate example chips for broader story coverage
207f884  v0.15.1: synthesis-strip permits bug — wrong field name
2d5598f  v0.15: dual-mode (Cloud + Edge) + expert-briefing dossier reframe
ad1f6d6  STATUS: refresh from May-2-v0.7 snapshot to May-6-v0.14.1 reality
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
