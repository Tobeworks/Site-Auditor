import os
import re
import threading
import time
from datetime import datetime, timezone

import httpx
from bs4 import BeautifulSoup

from auditor.checks.reviews import _host
from auditor.findings import finding

DATAFORSEO_URL = "https://api.dataforseo.com/v3/serp/google/organic/live/advanced"
CACHE_TTL = 24 * 3600  # dieselbe Domain nicht öfter als einmal am Tag abfragen (Kosten)
_GOOGLE_CACHE: dict[str, tuple[float, dict]] = {}
_CACHE_LOCK = threading.Lock()
OK = 20000  # DataForSEO meldet Erfolg und Fehler (z. B. 40200 bei leerem Guthaben) im Body, nicht im HTTP-Status


def _empty(status: str, query: str = "") -> dict:
    return {
        "status": status, "query": query, "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "title": None, "description": None, "display_url": None, "sitelinks": [],
    }


def _item_host(item: dict) -> str:
    """Die 'url' ist bei DataForSEO derzeit eine Google-Weiterleitung, die sichtbare Adresse steht in 'breadcrumb'."""
    crumb = (item.get("breadcrumb") or "").strip()
    host = _host(re.split(r"\s|›", crumb, maxsplit=1)[0]) if crumb else ""
    if not host:
        host = _host(item.get("url") or "")
    return "" if host == "google.com" else host


def fetch_google_result(domain: str) -> dict:
    """So zeigt Google die Domain bei der Suche nach ihrem Namen (Deutschland, Deutsch, Desktop). Wirft nie."""
    key = os.environ.get("DATAFORSEO_API_KEY")
    if not key:
        return _empty("disabled", domain)
    with _CACHE_LOCK:
        hit = _GOOGLE_CACHE.get(domain)
        if hit and time.time() - hit[0] < CACHE_TTL:
            return dict(hit[1])
    try:
        with httpx.Client(timeout=15) as client:
            r = client.post(
                DATAFORSEO_URL,
                headers={"Authorization": f"Basic {key}", "Content-Type": "application/json"},
                json=[{"keyword": domain, "location_code": 2276, "language_code": "de", "device": "desktop", "depth": 10}],
            )
        if r.status_code != 200:
            return _empty("error", domain)
        data = r.json()
        task = data["tasks"][0]
        if data.get("status_code") != OK or task.get("status_code") != OK:
            return _empty("error", domain)
        items = (task.get("result") or [{}])[0].get("items") or []
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError, AttributeError):
        return _empty("error", domain)

    result = _empty("not_found", domain)
    match = next((i for i in items if isinstance(i, dict) and i.get("type") == "organic" and _item_host(i) == domain), None)
    if match:
        result.update({
            "status": "found", "title": match.get("title"), "description": match.get("description"),
            "display_url": match.get("breadcrumb"),
            "sitelinks": [
                {"title": l.get("title"), "description": l.get("description")}
                for l in (match.get("links") or []) if isinstance(l, dict) and l.get("title")
            ],
        })
    with _CACHE_LOCK:
        _GOOGLE_CACHE[domain] = (time.time(), result)
    return dict(result)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("…", " ").replace("...", " ")).strip().lower()


def _words(text: str) -> set[str]:
    return set(re.findall(r"\w{2,}", (text or "").lower()))


def run(url: str, html: str, soup: BeautifulSoup, headers: dict) -> dict:
    try:
        domain = _host(url)
        result = fetch_google_result(domain)
        findings = []
        if result["status"] == "found":
            tag = soup.find("meta", attrs={"name": "description"})
            meta = (tag.get("content") or "").strip() if tag else ""
            g_desc = (result["description"] or "").strip()
            if meta and len(_norm(g_desc)) >= 20:
                nm, ng = _norm(meta), _norm(g_desc)
                if ng in nm or nm in ng:
                    findings.append(finding("GOO-01", "POSITIV", "Google zeigt deine Beschreibung", "Besucher lesen den Text, den du für die Suche gedacht hast."))
                elif len(meta) >= 120:  # kürzere Beschreibungen meldet schon SEO-02
                    findings.append(finding(
                        "GOO-01", "MITTEL", "Google zeigt eine andere Beschreibung als deine",
                        f'Deine Beschreibung: "{meta[:100]}". Google zeigt: "{g_desc[:100]}". Google nimmt Text von der Seite, wenn er besser zur Suche passt oder die Beschreibung zu allgemein ist.',
                        solution="Die Beschreibung konkreter formulieren, den wichtigsten Satz nach vorne stellen und zur Überschrift passend halten. Am Ende entscheidet Google.",
                    ))
            title_tag = soup.find("title")
            page_title = title_tag.get_text(strip=True) if title_tag else ""
            a, b = _words(page_title), _words(result["title"] or "")
            if a and b and len(a & b) / min(len(a), len(b)) < 0.5:
                findings.append(finding(
                    "GOO-02", "MITTEL", f'Google zeigt einen anderen Titel: "{result["title"]}" statt "{page_title}"',
                    "Google ersetzt Titel, die nicht zur Seite oder zur Suche passen, durch eigene.",
                    solution="Den Seitentitel (title-Tag) so formulieren, dass er zur Überschrift und zum Seiteninhalt passt.",
                ))
        result["findings"] = findings
        return result
    except Exception as e:
        return {"error": str(e)}
