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
        f"\n\nIMPORTANT: write ALL user-facing copy in {name}. This includes "
        f"summary, rationale, descriptions, narrative paragraphs, and bullet "
        f"text. Do NOT translate: official product names (e.g. \"NFIP flood "
        f"insurance\", \"Sewer / water-backup endorsement\"), proper nouns, "
        f"URLs, phone numbers, dollar amounts, or technical codes (e.g. "
        f"\"FEMA Zone X\", \"AEP\"). Keep JSON keys in English."
    )
