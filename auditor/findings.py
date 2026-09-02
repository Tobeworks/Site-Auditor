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
    timeframe: str | None = None,
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
    "LGL": "Trust & Legal",
    "A11": "UX & Funnel",
}
