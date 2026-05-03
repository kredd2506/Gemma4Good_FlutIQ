"""
Curated catalog of REAL flood insurance products and mitigation
resources, with verified contact info and current pricing.

Maintained by hand. Do NOT let the advisor agent invent product names
or prices — pass entries from this catalog into the prompt and let
Gemma 4 only choose which apply and write the plain-English rationale.

Last verified: 2026-05-02 (web sources: floodsmart.gov, fema.gov,
mwrd.org, chicago.gov/water).
"""

# Insurance products available in the US.
# `availability`: "us"  → nationwide
#                 list  → list of US state postal codes (e.g. ["IL", "TX"])
INSURANCE_PRODUCTS = [
    {
        "id": "homeowners_sewer_rider",
        "name": "Sewer / water-backup endorsement",
        "kind": "endorsement",
        "typical_cost": "$30-100/yr",
        "covers": (
            "Damage from water that backs up through floor drains, "
            "toilets, sinks, or sump pump failures."
        ),
        "does_not_cover": (
            "Surface flooding from rivers or rainwater entering "
            "above ground. That is the NFIP's job."
        ),
        "how_to_buy": (
            "Call your existing homeowners insurance agent and ask "
            "to ADD a sewer/water-backup endorsement. Confirm the "
            "coverage limit is at least $25,000."
        ),
        "availability": "us",
        "fits_when": [
            "address is in an urban area with combined or aging sewers",
            "any 311 basement-flooding reports nearby",
            "homeowner has a finished basement",
        ],
    },
    {
        "id": "nfip_standard",
        "name": "NFIP flood insurance",
        "kind": "federal_program",
        "typical_cost": "varies — quote at floodsmart.gov",
        "cost_note": (
            "Since Risk Rating 2.0 (April 2023), NFIP no longer has "
            "a separate 'Preferred Risk Policy.' Every property is "
            "individually priced — typically $400-700/yr in Zone X "
            "and higher in SFHA zones."
        ),
        "covers": (
            "Building up to $250K and contents up to $100K from "
            "surface flooding (overflowing rivers, storm surge, "
            "heavy rain pooling above ground)."
        ),
        "does_not_cover": (
            "Sewer backup, basement contents, mold, or living "
            "expenses while displaced (those need separate coverage)."
        ),
        "how_to_buy": (
            "Get a free, instant quote at floodsmart.gov. NFIP has a "
            "30-day waiting period before coverage starts, so don't "
            "wait for a forecast."
        ),
        "availability": "us",
        "fits_when": [
            "FEMA SFHA designation (Zone A, AE, V, VE) — usually required by lender",
            "Zone X but homeowner wants peace of mind",
            "in a community participating in the NFIP",
        ],
    },
    {
        "id": "private_flood",
        "name": "Private flood insurance",
        "kind": "private_market",
        "typical_cost": "varies — comparable to or above NFIP",
        "covers": (
            "Often broader than NFIP: higher building/contents "
            "limits, replacement cost coverage, additional living "
            "expenses if displaced."
        ),
        "does_not_cover": (
            "Read the policy carefully — exclusions vary by carrier."
        ),
        "how_to_buy": (
            "Major US providers include Neptune Flood "
            "(neptuneflood.com) and Wright Flood. An independent "
            "insurance broker can get quotes from several at once."
        ),
        "availability": "us",
        "fits_when": [
            "home value is well above NFIP's $250K building cap",
            "needs replacement-cost coverage that NFIP doesn't offer",
            "wants higher contents coverage than $100K",
        ],
    },
    {
        "id": "parametric_flood",
        "name": "Parametric flood insurance",
        "kind": "parametric",
        "typical_cost": "varies — typically $200-500/yr per coverage tier",
        "covers": (
            "A pre-agreed payout that triggers automatically when a "
            "sensor (or measured flood depth) exceeds a set threshold "
            "at the property — no claim adjuster, payout in days."
        ),
        "does_not_cover": (
            "Doesn't cover actual loss — just pays the agreed amount "
            "if the trigger fires. 'Basis risk' = mismatch between "
            "trigger and actual damage."
        ),
        "how_to_buy": (
            "FloodFlash (US program via select brokers) and Arbol "
            "are the most accessible options for residential. Most "
            "buyers go through a broker."
        ),
        "availability": "us",
        "fits_when": [
            "homeowner runs a small business out of the property",
            "needs fast payout for business interruption",
            "wants a top-up above NFIP that pays before adjuster visits",
        ],
    },
]


# City-specific verified resources. Keyed on canonical city name.
# When a homeowner's address resolves outside these cities, the
# advisor falls back to nationwide resources only.
CITY_RESOURCES = {
    "chicago": [
        {
            "name": "MWRD rain barrels",
            "what": (
                "The Metropolitan Water Reclamation District sells "
                "subsidized rain barrels to Cook County residents — "
                "$21.96, or $10.98 for seniors 65+. Limit 2 per "
                "household; free shipping."
            ),
            "contact_or_url": "mwrd.org/rain-barrels · 312-751-6633",
        },
        {
            "name": "CNT RainReady home assessment",
            "what": (
                "The Center for Neighborhood Technology offers free "
                "in-home flood-risk assessments for Chicago homeowners, "
                "with a personalized mitigation report."
            ),
            "contact_or_url": "rainready.cnt.org",
        },
        {
            "name": "Chicago Department of Water Management",
            "what": (
                "Report sewer backups, leaks, downspout questions, "
                "and request service. Use 311 for fastest response."
            ),
            "contact_or_url": "311 · 312-744-7000 · chicago.gov/water",
        },
        {
            "name": "FEMA Flood Map Service Center",
            "what": (
                "See your address's official FEMA flood zone, FIRM "
                "panel effective date, and download printable maps."
            ),
            "contact_or_url": "msc.fema.gov",
        },
    ],
}

# Resources that apply to any US address.
NATIONWIDE_RESOURCES = [
    {
        "name": "FEMA Flood Map Service Center",
        "what": (
            "See your address's official FEMA flood zone, FIRM panel "
            "effective date, and download printable maps."
        ),
        "contact_or_url": "msc.fema.gov",
    },
    {
        "name": "FloodSmart (NFIP quote tool)",
        "what": (
            "Free instant NFIP quote based on your address. Run by "
            "FEMA. Lists local agents who can write the policy."
        ),
        "contact_or_url": "floodsmart.gov",
    },
]


def resources_for_city(city: str) -> list[dict]:
    key = (city or "").strip().lower()
    seen = set()
    out = []
    for r in CITY_RESOURCES.get(key, []) + NATIONWIDE_RESOURCES:
        name = (r.get("name") or "").strip().lower()
        if name in seen:
            continue
        seen.add(name)
        out.append(r)
    return out


def products_available_in(state_code: str) -> list[dict]:
    """Filter the catalog by a 2-letter state code (currently all are 'us')."""
    out = []
    for p in INSURANCE_PRODUCTS:
        avail = p.get("availability")
        if avail == "us" or (isinstance(avail, list) and state_code in avail):
            out.append(p)
    return out
