import time
import concurrent.futures
from typing import Callable
import httpx
from bs4 import BeautifulSoup
from urllib.parse import urlparse

from auditor import scoring
from auditor.checks import (
    wordpress, wordpress_deep, seo, security, performance,
    broken_links, a11y, structured_data, markup, legal, tech_stack,
    social, hosting, dns, content_quality, ai_visibility, contact, accessibility_static, reviews, google_result,
    first_view, clarity,
)

OnProgress = Callable[[str, str], None]


def run_audit(
    url: str,
    skip: list[str] | None = None,
    on_progress: OnProgress | None = None,
    url_validator: Callable[[str], bool] | None = None,
    clarity_judge: Callable[[dict], dict | None] | None = None,
) -> dict:
    """clarity_judge: optional. Ohne ihn startet kein Browser und es gibt keinen Block `clarity`. Mit ihm liest ein Browser den
    ersten Handy-Bildschirm und der judge beantwortet, für wen das Angebot ist und was verkauft wird (siehe checks/clarity.py).
    url_validator: optional, wird für jedes Weiterleitungsziel der ersten Abfrage aufgerufen. Gibt es False zurück, wird
    nicht weiter gefolgt und der Audit endet wie bei einer nicht ladbaren Seite. Ein öffentlicher Dienst übergibt hier seine
    Prüfung auf öffentliche Adressen, sonst führt eine Weiterleitung auf interne Adressen zu SSRF."""
    skip = [s.lower() for s in (skip or [])]
    results = {}

    def notify(name: str, message: str):
        if on_progress:
            on_progress(name, message)

    notify("start", url)

    html, resp_headers, response_time_ms = _fetch(url, url_validator)

    if html is None:
        notify("error", "Seite konnte nicht geladen werden.")
        return {}

    if resp_headers.get("_fallback_used"):
        notify("warning", "HTTPS nicht verfügbar, weiter mit HTTP")

    soup = BeautifulSoup(html, "lxml")

    # Inject meta info into headers dict for modules to use
    resp_headers["_response_time_ms"] = response_time_ms
    resp_headers["_http_version"] = "HTTP/2" if "HTTP/2" in resp_headers.get("_raw_version", "") else "HTTP/1.1"

    # WordPress detection first
    notify("wordpress", "WordPress-Erkennung")
    wp_result = wordpress.run(url, html, soup, resp_headers)
    results["wordpress"] = wp_result

    # hosting + dns in parallel (no HTML needed), each one skippable on its own
    parallel = [(name, mod) for name, mod in (("hosting", hosting), ("dns", dns)) if name not in skip]
    if parallel:
        notify("hosting", "Hosting & E-Mail-Schutz analysieren..." if len(parallel) == 2
               else "Hosting analysieren..." if parallel[0][0] == "hosting" else "E-Mail-Schutz prüfen...")
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
            futures = {name: ex.submit(mod.run, url, "", None, resp_headers) for name, mod in parallel}
            for name, future in futures.items():
                results[name] = future.result()

    # WordPress deep (conditional)
    if wp_result.get("is_wordpress") and "wordpress_deep" not in skip:
        notify("wordpress_deep", "WordPress-Sicherheitscheck...")
        results["wordpress_deep"] = wordpress_deep.run(url, html, soup, resp_headers)

    # Sequential modules
    sequential = [
        ("seo", seo, "SEO analysieren..."),
        ("security", security, "Security-Headers prüfen..."),
        ("performance", performance, "Performance analysieren..."),
        ("broken_links", broken_links, "Links prüfen..."),
        ("structured_data", structured_data, "Strukturierte Daten prüfen..."),
        ("markup", markup, "HTML-Markup validieren..."),
        ("legal", legal, "Rechtliche Checks..."),
        ("tech_stack", tech_stack, "Tech-Stack erkennen..."),
        ("social", social, "Social & Crawlability prüfen..."),
        # Neue Module vor content_quality: das entfernt nav/header/footer/script aus der gemeinsamen soup.
        ("ai_visibility", ai_visibility, "KI-Crawler prüfen..."),
        ("contact", contact, "Kontaktweg prüfen..."),
        ("accessibility_static", accessibility_static, "Barrierefreiheit prüfen (Schnelltest)..."),
        ("reviews", reviews, "Bewertungen prüfen..."),
        ("google_result", google_result, "Google-Treffer abfragen..."),
        ("content_quality", content_quality, "Content-Qualität prüfen..."),
    ]

    for name, module, label in sequential:
        if name in skip:
            continue
        notify(name, label)
        results[name] = module.run(url, html, soup, resp_headers)

    # Klarheit auf den ersten Blick, nur mit judge. Jede Ausnahme ergibt "nicht beurteilbar", der Audit läuft weiter.
    if clarity_judge is not None and "clarity" not in skip:
        notify("clarity", "Ersten Eindruck prüfen...")
        try:
            results["clarity"] = clarity.run(first_view.collect(url, url_validator), clarity_judge)
        except Exception:
            results["clarity"] = {"stage": "nicht_beurteilbar", "reason": "failed", "audience": None, "offer": None}

    # a11y last (Playwright)
    if "a11y" not in skip:
        notify("a11y", "Barrierefreiheit prüfen (Playwright)...")
        results["a11y"] = a11y.run(url, html, soup, resp_headers)

    scoring.apply_effort(results)
    results["score"] = scoring.build_score(results)

    notify("done", "Analyse abgeschlossen")
    return results


class _BlockedRedirect(Exception):
    pass


def _get_following(client, url: str, url_validator, max_redirects: int = 5):
    """GET mit Weiterleitungen, bei denen jedes Ziel geprüft wird (httpx prüft sonst nur die erste Adresse)."""
    for _ in range(max_redirects + 1):
        r = client.get(url)
        location = r.headers.get("location")
        if r.is_redirect and location:
            url = str(r.url.join(location))
            if url_validator is not None and not url_validator(url):
                raise _BlockedRedirect(url)
            continue
        return r
    raise httpx.TooManyRedirects("zu viele Weiterleitungen")


def _fetch(url: str, url_validator=None) -> tuple[str | None, dict, int]:
    ua = {"User-Agent": "Mozilla/5.0 (compatible; site-auditor/1.0)"}
    parsed = urlparse(url)

    # Build candidate URLs: try as-given first, then HTTP fallback if HTTPS fails
    candidates = [url]
    if parsed.scheme == "https":
        candidates.append(url.replace("https://", "http://", 1))

    for candidate in candidates:
        for attempt in range(2):
            try:
                start = time.time()
                with httpx.Client(timeout=15, follow_redirects=False, http2=True, headers=ua, verify=False) as client:
                    r = _get_following(client, candidate, url_validator)
                    elapsed = int((time.time() - start) * 1000)
                    h = dict(r.headers)
                    h["_response_time_ms"] = elapsed
                    h["_raw_version"] = str(r.http_version)
                    h["_fallback_used"] = candidate != url
                    h["_status_code"] = r.status_code
                    return r.text, h, elapsed
            except _BlockedRedirect:
                return None, {}, 0
            except (httpx.ConnectError, httpx.TimeoutException, httpx.TooManyRedirects):
                if attempt == 1:
                    break
    return None, {}, 0
