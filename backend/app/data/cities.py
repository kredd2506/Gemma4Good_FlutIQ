"""
City registry for the local agent.

Each entry encodes everything the 311 + permits tools need to query
the city's Socrata-hosted open data: dataset IDs, the field names
used for category/cost/date/location, the actual flood-related
category values, and a short context blurb that gets injected into
the local-agent prompt so Gemma 4 has accurate sewer-system info
when it interprets the signals.

All entries verified live on 2026-05-04 against the cities' open-data
portals. The honesty-tax: most cities don't expose project cost in
their permits dataset, and not every city categorizes 311 floods
explicitly. Each config field documents what's actually available
so the dossier can degrade gracefully (e.g. show permit COUNT but
suppress the dollar narrative when no cost field exists).
"""
from typing import Optional


# Standardize state matching: accept full name OR 2-letter code.
def _state_match(input_state: str, codes: tuple[str, ...]) -> bool:
    s = (input_state or "").strip().lower()
    return any(s == c.lower() for c in codes)


CITIES: list[dict] = [
    # ---- CHICAGO --------------------------------------------------------
    {
        "id": "chicago",
        "name": "Chicago",
        "state_codes": ("IL", "Illinois"),
        "match_fn": lambda city, state: "chicago" in (city or "").lower() and _state_match(state, ("IL", "Illinois")),
        "context_blurb": (
            "Chicago has a combined sewer system covering ~80% of the city. "
            "Combined sewer overflows after ~0.67 in/hr of rain. 42% of Cook "
            "County is impervious surface. MWRD's Deep Tunnel (TARP) provides "
            "buffering but local sewers still bottleneck at neighborhood scale."
        ),
        "311": {
            "url": "https://data.cityofchicago.org/resource/v6vf-nfxy.json",
            "category_field": "sr_short_code",
            # Chicago uses short codes: WIB = Water in Basement, SFL = Street Flooding
            "flood_categories": ("WIB", "SFL"),
            "category_in_clause": "sr_short_code in('WIB','SFL')",
            "date_field": "created_date",
            "location_field": "location",
            "select_fields": "sr_short_code,created_date,street_address,ward",
            "address_field_template": "street_address",
        },
        "permits": {
            "url": "https://data.cityofchicago.org/resource/ydr8-5enu.json",
            "permit_type_field": "permit_type",
            "permit_type_values": (
                "PERMIT - NEW CONSTRUCTION",
                "PERMIT - RENOVATION/ALTERATION",
            ),
            "cost_field": "reported_cost",
            "date_field": "issue_date",
            "location_field": "location",
            "select_fields": (
                "permit_type,work_description,reported_cost,issue_date,"
                "latitude,longitude,street_number,street_direction,"
                "street_name,total_fee"
            ),
            "address_keys": ("street_number", "street_direction", "street_name"),
            "new_construction_marker": "NEW CONSTRUCTION",
            "renovation_marker": "RENOVATION",
            "has_cost": True,
        },
    },
    # ---- NEW YORK CITY --------------------------------------------------
    {
        "id": "nyc",
        "name": "New York City",
        "state_codes": ("NY", "New York"),
        "match_fn": lambda city, state: any(t in (city or "").lower() for t in ("new york", "manhattan", "brooklyn", "queens", "bronx", "staten island")) and _state_match(state, ("NY", "New York")),
        "context_blurb": (
            "NYC has combined sewer systems across 60% of the city — including "
            "all of Manhattan, much of Brooklyn, and parts of Queens and the "
            "Bronx. Storm intensity above ~1.5 in/hr triggers combined-sewer "
            "overflows into NY Harbor and basement backups. NYC DEP's bluebelts "
            "and grey infrastructure are unevenly distributed."
        ),
        "311": {
            "url": "https://data.cityofnewyork.us/resource/erm2-nwe9.json",
            "category_field": "complaint_type",
            # NYC complaint_type values verified 2026-05 (top flood-related)
            "flood_categories": ("Sewer", "Sewer Maintenance"),
            "category_in_clause": "complaint_type in('Sewer','Sewer Maintenance')",
            "date_field": "created_date",
            "location_field": "location",
            # NYC uses lat/lon directly:
            "select_fields": "complaint_type,descriptor,created_date,incident_address,borough",
            "address_field_template": "incident_address",
        },
        # NYC permits intentionally DEFERRED. The DOB datasets are fragmented:
        #   ipu4-2q9a (legacy "DOB Permit Issuance") — most recent NB rows
        #     are from 2022; the dataset stopped being updated regularly.
        #   rbx6-tga4 (DOB NOW: Build – Approved Permits) — has cost
        #     (estimated_job_costs) and lat/lon, but NO date column
        #     suitable for "last 3 years" filtering.
        #   w9ak-ipjd (Active Construction Permits) — has filing_date and
        #     initial_cost in the right format, but is filtered to currently-
        #     active permits, so the historical 3-year window is empty for
        #     most areas.
        # The right fix is a custom NYC client that joins multiple datasets;
        # for the hackathon scope NYC ships with 311-only and the dossier
        # honestly says permits-deferred.
        "permits": None,
    },
    # ---- SAN FRANCISCO --------------------------------------------------
    {
        "id": "sf",
        "name": "San Francisco",
        "state_codes": ("CA", "California"),
        "match_fn": lambda city, state: "san francisco" in (city or "").lower() and _state_match(state, ("CA", "California")),
        "context_blurb": (
            "San Francisco operates a fully combined sewer system citywide — "
            "the only major California city to do so. Heavy rain plus high "
            "tide concentrates overflows. SF Public Utilities Commission has "
            "documented chronic flooding hotspots in Mission, Bayview, and "
            "the South of Market areas."
        ),
        "311": {
            "url": "https://data.sfgov.org/resource/vw6y-z8j6.json",
            "category_field": "service_name",
            "flood_categories": ("Sewer Issues", "Sewer"),
            "category_in_clause": "service_name in('Sewer Issues','Sewer')",
            "date_field": "requested_datetime",
            "location_field": "point",
            "select_fields": "service_name,service_subtype,requested_datetime,address",
            "address_field_template": "address",
        },
        "permits": {
            "url": "https://data.sfgov.org/resource/i98e-djp9.json",
            "permit_type_field": "permit_type_definition",
            "permit_type_values": (
                "new construction",
                "new construction wood frame",
                "additions alterations or repairs",
            ),
            "cost_field": "estimated_cost",
            "cost_is_string": True,  # SF stores estimated_cost as text
            "date_field": "issued_date",
            "location_field": "location",  # SF permits has a real Socrata Point column
            "select_fields": (
                "permit_type,permit_type_definition,description,estimated_cost,"
                "revised_cost,issued_date,filed_date,street_number,street_name,"
                "street_suffix,zipcode"
            ),
            "address_keys": ("street_number", "street_name", "street_suffix"),
            "new_construction_marker": "new construction",
            "renovation_marker": "alterations",
            "has_cost": True,
        },
    },
    # ---- LOS ANGELES ----------------------------------------------------
    {
        "id": "la",
        "name": "Los Angeles",
        "state_codes": ("CA", "California"),
        "match_fn": lambda city, state: any(t in (city or "").lower() for t in ("los angeles", "los-angeles")) and _state_match(state, ("CA", "California")),
        "context_blurb": (
            "Los Angeles has a separated storm-sanitary sewer system — the "
            "two pipe networks don't co-mingle, so basement sewer-backup "
            "flooding is rare. The dominant LA flood mode is FLASH FLOODING "
            "during winter atmospheric-river events, when concrete-channelized "
            "rivers (LA River, Ballona Creek) and soft-bottomed creeks rise "
            "rapidly. Hillside debris flows after wildfire are a separate "
            "wet-season hazard."
        ),
        "311": None,  # LA's 311 dataset doesn't categorize floods cleanly enough; deferred
        "permits": {
            "url": "https://data.lacity.org/resource/pi9x-tg5x.json",
            "permit_type_field": "permit_type",
            "permit_type_values": ("Bldg-New", "Bldg-Alter/Repair", "Bldg-Addition"),
            "cost_field": "valuation",
            "cost_is_string": True,  # LA stores valuation as text
            "date_field": "issue_date",
            "location_field": None,
            "select_fields": (
                "permit_type,permit_sub_type,work_desc,valuation,issue_date,"
                "primary_address,zip_code,lat,lon"
            ),
            "address_keys": ("primary_address",),
            "new_construction_marker": "New",
            "renovation_marker": "Alter",
            "has_cost": True,
            "lat_field": "lat",
            "lon_field": "lon",
            "lat_lon_is_string": True,  # LA stores lat/lon as text — need cast
        },
    },
    # ---- AUSTIN ---------------------------------------------------------
    {
        "id": "austin",
        "name": "Austin",
        "state_codes": ("TX", "Texas"),
        "match_fn": lambda city, state: "austin" in (city or "").lower() and _state_match(state, ("TX", "Texas")),
        "context_blurb": (
            "Austin has separated storm and sanitary sewers, but the storm "
            "drain system is undersized for the increasingly extreme rainfall "
            "events of the post-2010 Texas climate. Onion Creek and Williamson "
            "Creek have historic flash-flood corridors. Austin's hilly topo "
            "concentrates runoff into well-known low-point intersections — the "
            "city publishes a 'Flood Early Warning System' map for these spots."
        ),
        "311": {
            "url": "https://data.austintexas.gov/resource/xwdj-i9he.json",
            "category_field": "sr_type_desc",
            "flood_categories": (
                "Flooding Current (Non-Emergency)",
                "Flooding - Past",
                "WPD - Flooding Current",
                "WPD - Flooding Past",
                "WPD - Channels/Creek/Drainage Issues",
                "WPD - Storm Drain Services",
            ),
            "category_in_clause": (
                "sr_type_desc in("
                "'Flooding Current (Non-Emergency)',"
                "'Flooding - Past',"
                "'WPD - Flooding Current',"
                "'WPD - Flooding Past',"
                "'WPD - Channels/Creek/Drainage Issues',"
                "'WPD - Storm Drain Services'"
                ")"
            ),
            "date_field": "sr_created_date",
            "location_field": "sr_location_lat_long",  # real Point column
            "select_fields": "sr_type_desc,sr_created_date,sr_location",
            "address_field_template": "sr_location",
        },
        "permits": {
            "url": "https://data.austintexas.gov/resource/3syk-w9eu.json",
            "permit_type_field": "permittype",
            # Austin permittype: BP=building, MP=mechanical, etc. We want the
            # construction-relevant ones via permit_class_mapped + work_class.
            "permit_type_values": ("BP",),
            "cost_field": None,  # Austin permits dataset has no cost field
            "date_field": "issue_date",
            "location_field": "location",
            "select_fields": (
                "permittype,permit_type_desc,permit_class_mapped,work_class,"
                "description,issue_date,permit_location,latitude,longitude,"
                "original_address1,original_zip"
            ),
            "address_keys": ("original_address1",),
            "new_construction_marker": "New",
            "renovation_marker": "Remodel",
            "has_cost": False,
            "lat_field": "latitude",
            "lon_field": "longitude",
        },
    },
]


def find_city(city: str, state: str) -> Optional[dict]:
    """Look up a registry entry for the given geocoded city/state, or None."""
    for entry in CITIES:
        try:
            if entry["match_fn"](city, state):
                return entry
        except Exception:
            continue
    return None


def supported_city_names() -> list[str]:
    return [c["name"] for c in CITIES]
