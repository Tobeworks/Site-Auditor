"""Teilscores, Gesamtnote, "Das zuerst" und Aufwandsspannen.
Rechnung und Begründung: docs/superpowers/specs/2026-09-02-scoring-roadmap-competitor-design.md (Abschnitte 1 und 2)."""
from auditor.findings import CATEGORY_MAP, EFFORT_BY_SEVERITY, MODULE_PREFIX

DEDUCTION = {"KRITISCH": 3, "HOCH": 1.5, "MITTEL": 0.5, "POSITIV": 0}
SEVERITY_ORDER = {"KRITISCH": 0, "HOCH": 1, "MITTEL": 2}
FORMULA = (
    "Jede Kategorie startet bei 10 Punkten. Abzug je Befund: kritisch 3, hoch 1,5, mittel 0,5, positive Befunde 0. "
    "Die Gesamtnote ist der Durchschnitt der geprüften Kategorien. Kategorien ohne geprüftes Modul zählen nicht."
)


def _modules_with_findings(results: dict):
    for module, data in results.items():
        if isinstance(data, dict) and "error" not in data and isinstance(data.get("findings"), list):
            yield module, data["findings"]


def open_findings(results: dict) -> list[tuple[str, dict]]:
    """Alle Befunde, die nicht POSITIV sind, als (Modul, Befund)."""
    return [(m, f) for m, findings in _modules_with_findings(results) for f in findings if f["severity"] != "POSITIV"]


def apply_effort(results: dict) -> None:
    """Setzt fehlende Aufwandsspannen und Zeithorizonte je Schweregrad. Vorhandene Werte bleiben. Schätzung, kein Angebot."""
    for _, f in open_findings(results):
        effort, timeframe = EFFORT_BY_SEVERITY[f["severity"]]
        if f.get("effort_days") is None:
            f["effort_days"] = effort
        if f.get("timeframe") is None:
            f["timeframe"] = timeframe


def _category(finding_id: str) -> str | None:
    return CATEGORY_MAP.get(finding_id.split("-")[0])


def build_score(results: dict) -> dict:
    checked = {
        CATEGORY_MAP[MODULE_PREFIX[module]]
        for module, _ in _modules_with_findings(results) if module in MODULE_PREFIX
    }
    deductions = []
    totals = {category: 10.0 for category in checked}
    for _, findings in _modules_with_findings(results):
        for f in findings:
            category, points = _category(f["id"]), DEDUCTION.get(f["severity"], 0)
            if category in totals and points:
                totals[category] = max(0.0, totals[category] - points)
                deductions.append({"id": f["id"], "category": category, "severity": f["severity"], "points": points})
    categories = {c: round(v, 1) for c, v in sorted(totals.items())}
    overall = round(sum(categories.values()) / len(categories), 1) if categories else None

    def order(item):
        _, f = item
        effort = f.get("effort_days") or (0, 0)
        return SEVERITY_ORDER[f["severity"]], effort[0], f["id"]

    first = [
        {"id": f["id"], "severity": f["severity"], "finding": f["finding"], "solution": f["solution"],
         "effort_days": list(f["effort_days"]) if f.get("effort_days") else None, "timeframe": f.get("timeframe")}
        for _, f in sorted(open_findings(results), key=order)[:3]
    ]
    return {"categories": categories, "overall": overall, "deductions": deductions, "formula": FORMULA, "first": first}
