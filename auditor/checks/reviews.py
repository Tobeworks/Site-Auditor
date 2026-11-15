import json
import re
from bs4 import BeautifulSoup

from auditor.findings import finding

# Bekannte Bewertungs-Widgets, erkannt an ihrer Einbindung (Skript, iframe, Klassenname).
WIDGETS = {
    "trustindex": "Trustindex",
    "elfsight": "Elfsight",
    "embedsocial": "EmbedSocial",
    "trustpilot": "Trustpilot",
    "provenexpert": "ProvenExpert",
}
GOOGLE_REVIEW_LINK = re.compile(r"g\.page/|google\.[a-z.]+/maps|search\.google\.com/local/reviews", re.I)
TESTIMONIAL_HEADING = re.compile(
    r"kundenstimmen|das sagen (unsere )?kunden|kundenbewertung|bewertungen|referenzen|testimonials|rezensionen", re.I
)


def _walk(node):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


def _schema_reviews(soup: BeautifulSoup) -> bool:
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            data = json.loads(script.string or "")
        except (ValueError, TypeError):
            continue
        for obj in _walk(data):
            types = obj.get("@type")
            types = types if isinstance(types, list) else [types]
            if any(t in ("Review", "AggregateRating") for t in types) or "aggregateRating" in obj or "review" in obj:
                return True
    return any(
        "aggregaterating" in (el.get("itemprop") or "").lower() or str(el.get("itemtype") or "").lower().endswith("/review")
        for el in soup.find_all(attrs={"itemprop": True}) + soup.find_all(attrs={"itemtype": True})
    )


def _widgets(soup: BeautifulSoup) -> list[str]:
    haystack = []
    for tag in soup.find_all(["script", "iframe"]):
        haystack.append((tag.get("src") or "").lower())
    for tag in soup.find_all(class_=True):
        haystack.append(" ".join(tag.get("class")).lower())
    joined = " ".join(haystack)
    return [name for key, name in WIDGETS.items() if key in joined]


def _google_default() -> dict:
    return {"status": "disabled", "rating": None, "count": None, "name": None, "address": None, "phone": None}


def run(url: str, html: str, soup: BeautifulSoup, headers: dict) -> dict:
    try:
        schema = _schema_reviews(soup)
        widgets = _widgets(soup)
        google_link = any(GOOGLE_REVIEW_LINK.search(a["href"]) for a in soup.find_all("a", href=True))
        testimonial = any(
            TESTIMONIAL_HEADING.search(h.get_text(" ", strip=True)) for h in soup.find_all(["h1", "h2", "h3", "h4"])
        )

        visible = bool(widgets or google_link or testimonial)
        findings = []
        if schema and not visible:
            findings.append(finding(
                "REV-01", "MITTEL", "Bewertungs-Markup ohne sichtbare Bewertungen",
                "Google erwartet, dass Bewertungen aus dem Markup auch auf der Seite zu sehen sind. Sonst kann das Markup ignoriert werden.",
                solution="Die Bewertungen sichtbar auf der Seite zeigen oder das Bewertungs-Markup entfernen.",
            ))
        if visible:
            source = ", ".join(widgets) if widgets else ("Google" if google_link else "Textabschnitt")
            findings.append(finding("REV-05", "POSITIV", f"Bewertungen auf der Seite erkannt ({source})", "Besucher sehen, was andere über dich sagen."))

        return {
            "schema_reviews": schema, "widgets": widgets, "google_link": google_link,
            "testimonial_section": testimonial, "google": _google_default(), "findings": findings,
        }
    except Exception as e:
        return {"error": str(e)}
