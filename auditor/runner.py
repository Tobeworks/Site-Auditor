import time
import concurrent.futures
from typing import Callable
import httpx
from bs4 import BeautifulSoup
from urllib.parse import urlparse

from auditor.checks import (
    wordpress, wordpress_deep, seo, security, performance,
    broken_links, a11y, structured_data, markup, legal, tech_stack,
    social, hosting, dns, content_quality,
)

OnProgress = Callable[[str, str], None]


def run_audit(url: str, skip: list[str] | None = None, on_progress: OnProgress | None = None) -> dict:
    skip = [s.lower() for s in (skip or [])]
    results = {}

    def notify(name: str, message: str):
        if on_progress:
            on_progress(name, message)

    notify("start", url)

    html, resp_headers, response_time_ms = _fetch(url)

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

    # hosting + dns in parallel (no HTML needed)
    if "hosting" not in skip:
        notify("hosting", "Hosting & DNS analysieren...")
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
            f_hosting = ex.submit(hosting.run, url, "", None, resp_headers)
            f_dns = ex.submit(dns.run, url, "", None, resp_headers)
            results["hosting"] = f_hosting.result()
            results["dns"] = f_dns.result()

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
        ("content_quality", content_quality, "Content-Qualität prüfen..."),
    ]

    for name, module, label in sequential:
        if name in skip:
            continue
        notify(name, label)
        results[name] = module.run(url, html, soup, resp_headers)

    # a11y last (Playwright)
    if "a11y" not in skip:
        notify("a11y", "Barrierefreiheit prüfen (Playwright)...")
        results["a11y"] = a11y.run(url, html, soup, resp_headers)

    notify("done", "Analyse abgeschlossen")
    return results


def _fetch(url: str) -> tuple[str | None, dict, int]:
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
                with httpx.Client(timeout=15, follow_redirects=True, http2=True, headers=ua, verify=False) as client:
                    r = client.get(candidate)
                    elapsed = int((time.time() - start) * 1000)
                    h = dict(r.headers)
                    h["_response_time_ms"] = elapsed
                    h["_raw_version"] = str(r.http_version)
                    h["_fallback_used"] = candidate != url
                    return r.text, h, elapsed
            except (httpx.ConnectError, httpx.TimeoutException):
                if attempt == 1:
                    break
    return None, {}, 0
