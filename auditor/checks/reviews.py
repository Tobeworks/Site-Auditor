import json
import os
import re
import threading
import time
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from auditor.checks.contact import PHONE_RE, _visible_text
from auditor.findings import finding

PLACES_URL = "https://places.googleapis.com/v1/places:searchText"
FIELD_MASK = (
    "places.displayName,places.formattedAddress,places.nationalPhoneNumber,"
    "places.websiteUri,places.rating,places.userRatingCount"
)
CACHE_TTL = 24 * 3600  # dieselbe Domain nicht öfter als einmal am Tag abfragen (Kosten)
_PLACES_CACHE: dict[str, tuple[float, dict]] = {}
_CACHE_LOCK = threading.Lock()

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


def _google_default(status: str = "disabled") -> dict:
    return {"status": status, "rating": None, "count": None, "name": None, "address": None, "phone": None}


def _host(value: str) -> str:
    try:
        host = (urlparse(value if "//" in value else "//" + value).hostname or "").lower()
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def _business(soup: BeautifulSoup, domain: str) -> tuple[str, str | None]:
    """Firmenname und Ort für die Suche: JSON-LD, sonst og:site_name, sonst Titel, sonst Domain."""
    name = locality = None
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            data = json.loads(script.string or "")
        except (ValueError, TypeError):
            continue
        for obj in _walk(data):
            if isinstance(obj.get("name"), str) and isinstance(obj.get("address"), dict):
                return obj["name"].strip(), (obj["address"].get("addressLocality") or None)
            if name is None and isinstance(obj.get("name"), str) and obj.get("@type") in ("Organization", "LocalBusiness"):
                name = obj["name"].strip()
    if not name:
        tag = soup.find("meta", attrs={"property": "og:site_name"})
        name = (tag.get("content") or "").strip() if tag else ""
    if not name and soup.find("title"):
        name = re.split(r"\s[|·\-–—:]\s", soup.find("title").get_text(strip=True))[0].strip()
    return name or domain, locality


def fetch_places(name: str, locality: str | None, domain: str) -> dict:
    """Google-Eintrag der Firma, nur wenn dessen Website dieselbe Domain hat. Wirft nie."""
    key = os.environ.get("GOOGLE_PLACES_API_KEY")
    if not key:
        return _google_default()
    with _CACHE_LOCK:
        hit = _PLACES_CACHE.get(domain)
        if hit and time.time() - hit[0] < CACHE_TTL:
            return dict(hit[1])
    try:
        with httpx.Client(timeout=8) as client:
            r = client.post(
                PLACES_URL,
                headers={"X-Goog-Api-Key": key, "X-Goog-FieldMask": FIELD_MASK, "Content-Type": "application/json"},
                json={"textQuery": f"{name} {locality or domain}", "languageCode": "de", "regionCode": "DE"},
            )
        if r.status_code != 200:
            return _google_default("error")
        places = r.json().get("places") or []
        if not isinstance(places, list):
            return _google_default("error")
    except (httpx.HTTPError, ValueError, AttributeError):
        return _google_default("error")

    match = next((p for p in places if isinstance(p, dict) and _host(p.get("websiteUri") or "") == domain), None)
    if match is None:
        result = _google_default("not_matched")
    else:
        result = {
            "status": "found", "rating": match.get("rating"), "count": match.get("userRatingCount"),
            "name": (match.get("displayName") or {}).get("text"), "address": match.get("formattedAddress"),
            "phone": match.get("nationalPhoneNumber"),
        }
    with _CACHE_LOCK:
        _PLACES_CACHE[domain] = (time.time(), result)
    return dict(result)


def _norm_phone(value: str) -> str:
    digits = re.sub(r"\D", "", re.sub(r"\(0\)", "", value))
    if digits.startswith("0049"):
        return "0" + digits[4:]
    return "0" + digits[2:] if digits.startswith("49") else digits


def _compare_with_google(soup: BeautifulSoup, google: dict) -> list:
    """Telefon und Postleitzahl der Seite gegen den Google-Eintrag. Nur wenn die Seite selbst Angaben macht."""
    findings = []
    text = _visible_text(soup)
    raw_phones = [m.group(0).strip() for m in PHONE_RE.finditer(text)]
    raw_phones += [a["href"][4:] for a in soup.find_all("a", href=True) if a["href"].lower().startswith("tel:")]
    page_phones = {_norm_phone(p) for p in raw_phones}
    if google["phone"] and page_phones and _norm_phone(google["phone"]) not in page_phones:
        findings.append(finding(
            "REV-03", "MITTEL", f"Telefonnummer weicht ab: Seite {raw_phones[0]}, Google {google['phone']}",
            "Verschiedene Nummern auf der Seite und im Google-Eintrag verunsichern Kunden und Google.",
            solution="Die Nummer auf der Seite und im Google-Eintrag angleichen.",
        ))
    google_plz = re.search(r"\b(\d{5})\b", google["address"] or "")
    page_plz = set(re.findall(r"\b(\d{5})\s+[A-ZÄÖÜ][a-zäöüß]", text))
    if google_plz and page_plz and google_plz.group(1) not in page_plz:
        findings.append(finding(
            "REV-04", "MITTEL", f"Adresse weicht ab: Seite nennt PLZ {', '.join(sorted(page_plz))}, Google {google_plz.group(1)}",
            "Eine andere Adresse auf der Seite als im Google-Eintrag verunsichert Kunden und Google.",
            solution="Adresse auf der Seite und im Google-Eintrag angleichen.",
        ))
    return findings


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

        domain = _host(url)
        google = _google_default()
        if os.environ.get("GOOGLE_PLACES_API_KEY"):
            name, locality = _business(soup, domain)
            google = fetch_places(name, locality, domain)
        if google["status"] == "found":
            if google["count"]:
                numbers = f"{google['rating']:.1f}".replace(".", ",") + f" von 5 Sternen bei {google['count']} Bewertungen"
                if visible:
                    findings.append(finding("REV-02", "POSITIV", f"Google-Bewertungen vorhanden ({numbers}) und auf der Seite sichtbar", "Besucher sehen, was andere über dich sagen."))
                else:
                    findings.append(finding(
                        "REV-02", "MITTEL", f"Bei Google hast du {numbers}, auf der Seite sind keine zu sehen",
                        "Gute Bewertungen bei Google überzeugen Besucher, wenn sie sie auch auf deiner Seite sehen.",
                        solution="Die Google-Bewertungen mit einem Bewertungs-Widget zeigen oder zumindest auf deinen Google-Eintrag verlinken.",
                    ))
            findings += _compare_with_google(soup, google)
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
            "testimonial_section": testimonial, "google": google, "findings": findings,
        }
    except Exception as e:
        return {"error": str(e)}
