"""
Languages we expose for the dossier.

Selection rationale: the six non-English languages here cover roughly
80% of non-English-speaking households in US flood-prone metros
(USCB ACS 2022 home-language statistics).

The advisor and risk agents translate user-facing copy into the
chosen language. Product names ("NFIP flood insurance", "Sewer /
water-backup endorsement") and external resource names stay in
English on purpose — those are the strings the homeowner needs to
say or search to actually buy the product.
"""

# Each entry: code → (English label, native label, full English name
# for the prompt directive)
LANGUAGES: dict[str, tuple[str, str, str]] = {
    "en": ("English", "English", "English"),
    "es": ("Spanish", "Español", "Spanish (Latin American)"),
    "zh": ("Mandarin", "中文", "Mandarin Chinese (Simplified)"),
    "vi": ("Vietnamese", "Tiếng Việt", "Vietnamese"),
    "ht": ("Haitian Creole", "Kreyòl ayisyen", "Haitian Creole"),
    "ar": ("Arabic", "العربية", "Arabic"),
    "tl": ("Tagalog", "Tagalog", "Tagalog"),
}


def normalize(code: str | None) -> str:
    """Coerce a possibly-stale or unknown code to a supported one."""
    if not code:
        return "en"
    code = code.lower().split("-")[0]  # 'es-MX' → 'es'
    return code if code in LANGUAGES else "en"


def prompt_directive(code: str) -> str:
    """The string to inject into a system/user prompt to set output language."""
    code = normalize(code)
    if code == "en":
        return ""
    name = LANGUAGES[code][2]
    return (
        f"\n\nIMPORTANT: write ALL user-facing prose in {name}. This includes "
        f"the summary, rationale, descriptions, narrative paragraphs, "
        f"bullet text, and any plain-English explanation a reader sees.\n\n"
        f"Do NOT translate the items below. They pass through a strict "
        f"parser that only accepts the original English values; translating "
        f"them causes the entry to be silently dropped from the dossier:\n"
        f"- JSON keys (always English — never translate field names)\n"
        f"- Enum / identifier values inside JSON. These are technical labels, "
        f"not prose. Copy them LETTER FOR LETTER from the spec/catalog:\n"
        f"    product_id  (e.g. \"nfip_standard\", \"homeowners_sewer_rider\")\n"
        f"    bucket      (\"drainage\" | \"infiltration\" | \"barrier\")\n"
        f"    cite        (\"FEMA\" | \"311\" | \"Permits\" | \"City sewer\" | "
        f"\"Satellite\" | \"Street view\" | \"NRI\" | \"USGS/NOAA\")\n"
        f"    priority    (\"start_here\" | \"also_consider\" | \"only_if\")\n"
        f"    effort      (\"diy\" | \"contractor\" | \"professional\")\n"
        f"    impact      (\"low\" | \"medium\" | \"high\")\n"
        f"- Official product names the user must repeat verbatim to actually "
        f"buy the product (e.g. \"NFIP flood insurance\", \"Sewer / "
        f"water-backup endorsement\")\n"
        f"- Proper nouns, URLs, phone numbers, dollar amounts, technical "
        f"codes (e.g. \"FEMA Zone X\", \"AEP\", \"NRI\")"
    )
