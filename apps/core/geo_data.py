"""Geographic and Locality Static Validation Sets for apps.core.

Defines ISO-3166-1 country codes, US state postal abbreviations,
system subdomains, and jurisdiction depth tiers per SPEC-008.
"""

from __future__ import annotations

# ISO-3166-1 alpha-2 lowercase country codes
VALID_COUNTRIES: frozenset[str] = frozenset({
    "us", "uk", "ca", "mx", "br", "de", "fr", "es", "it", "jp",
    "cn", "in", "au", "ru", "za", "kr", "se", "no", "fi", "dk",
    "nl", "be", "at", "ch", "pt", "ie", "nz", "sg", "il", "ae",
    "sa", "eg", "ng", "ke", "gh", "tz", "ar", "cl", "co", "pe",
    "ve", "ec", "bo", "py", "uy", "cr", "pa", "cu", "jm", "tt",
    "ht", "do", "hn", "sv", "ni", "gt", "bz", "pr", "gl", "pl",
    "cz", "ro", "hu", "ee", "lv", "lt", "is",
})

# Two-letter US state and territory postal abbreviations (lowercase)
VALID_US_STATES: frozenset[str] = frozenset({
    "al", "ak", "az", "ar", "ca", "co", "ct", "de", "fl", "ga",
    "hi", "id", "il", "in", "ia", "ks", "ky", "la", "me", "md",
    "ma", "mi", "mn", "ms", "mo", "mt", "ne", "nv", "nh", "nj",
    "nm", "ny", "nc", "nd", "oh", "ok", "or", "pa", "ri", "sc",
    "sd", "tn", "tx", "ut", "vt", "va", "wa", "wv", "wi", "wy",
    "dc", "pr", "vi", "gu", "as", "mp",
})

# Subdomains reserved for system operations (exempt from geographic containment)
SYSTEM_SUBDOMAINS: frozenset[str] = frozenset({
    "api", "admin", "static", "media", "ws", "relay", "auth", "blossom", "mods", "devs",
})

# Hierarchical jurisdiction depth mappings
JURISDICTION_TIERS: dict[int, str] = {
    1: "country",
    2: "state",
    3: "county",
    4: "city",
    5: "ward",
}
