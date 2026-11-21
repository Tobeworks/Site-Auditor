"""Shared Finding data model for every check module.
See docs/superpowers/specs/2026-09-02-findings-model-and-new-checks-design.md
"""
from typing import TypedDict, Literal

Severity = Literal["KRITISCH", "HOCH", "MITTEL", "POSITIV"]


class Finding(TypedDict):
    id: str
    severity: Severity
    finding: str
    impact: str
    solution: str | None
    effort_days: tuple[float, float] | None
    timeframe: Literal["kurzfristig", "mittelfristig", "langfristig"] | None


def finding(
    id: str,
    severity: Severity,
    text: str,
    impact: str,
    solution: str | None = None,
    effort_days: tuple[float, float] | None = None,
    timeframe: Literal["kurzfristig", "mittelfristig", "langfristig"] | None = None,
) -> Finding:
    """Build a Finding. Raises ValueError if severity/solution are inconsistent
    (POSITIV must not carry a solution, everything else must)."""
    if severity == "POSITIV" and solution is not None:
        raise ValueError(f"POSITIV finding '{id}' must not carry a solution")
    if severity != "POSITIV" and solution is None:
        raise ValueError(f"non-POSITIV finding '{id}' requires a solution")
    return {
        "id": id,
        "severity": severity,
        "finding": text,
        "impact": impact,
        "solution": solution,
        "effort_days": effort_days,
        "timeframe": timeframe,
    }


# Welcher Kennungs-Präfix gehört zu welchem Modul. 'wordpress' fehlt absichtlich: die Erkennung läuft immer
# und sagt nichts darüber, ob eine Kategorie geprüft wurde.
MODULE_PREFIX: dict[str, str] = {
    "seo": "SEO", "structured_data": "SDA", "performance": "PRF", "security": "SEC", "hosting": "HST",
    "social": "SOC", "broken_links": "LNK", "markup": "MKP", "tech_stack": "TCH", "wordpress_deep": "WPD",
    "dns": "DNS", "content_quality": "CNT", "legal": "LGL", "a11y": "A11", "ai_visibility": "KIS",
    "contact": "KON", "accessibility_static": "BAR", "reviews": "REV", "google_result": "GOO", "clarity": "KLA", "ux": "UXF",
}

# Standard-Aufwandsspanne in Personentagen und Zeithorizont je Schweregrad (Schätzung, kein Angebot).
EFFORT_BY_SEVERITY = {
    "KRITISCH": ((0.5, 1.5), "kurzfristig"),
    "HOCH": ((0.25, 1.0), "kurzfristig"),
    "MITTEL": ((0.1, 0.5), "mittelfristig"),
}

# Maps each module's Kennung prefix to one of the 7 Paket-4 scoring categories.
# Not consumed in Paket 1+2 — kept here so Paket 4 doesn't have to re-derive it.
CATEGORY_MAP: dict[str, str] = {
    "SEO": "OnPage-SEO",
    "SDA": "OnPage-SEO",
    "PRF": "Performance",
    "SEC": "Sicherheit & Stack",
    "HST": "Sicherheit & Stack",
    "SOC": "Technik & Index",
    "LNK": "Technik & Index",
    "MKP": "Technik & Index",
    "TCH": "Technik & Index",
    "WPR": "Technik & Index",
    "WPD": "Technik & Index",
    "DNS": "Technik & Index",
    "CNT": "Content & Sichtbarkeit",
    "KIS": "KI-Bereitschaft",
    "KON": "Bedienbarkeit",
    "BAR": "Bedienbarkeit",
    "REV": "Trust & Legal",
    "GOO": "OnPage-SEO",
    "LGL": "Trust & Legal",
    "A11": "Bedienbarkeit",
    "UXF": "Bedienbarkeit",
    "KLA": "Verständlichkeit",
}


def severity_by_share(count: int, total: int, base: str = "MITTEL") -> str:
    """Ein Mangel an einzelnen Stellen ist ein kleiner Fehler, der halbe Seite betroffen ein großer: ab 3 Stellen und der Hälfte wird HOCH."""
    return "HOCH" if base == "MITTEL" and count >= 3 and total and count / total >= 0.5 else base
