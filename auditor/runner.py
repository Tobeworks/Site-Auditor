import time
import concurrent.futures
import httpx
from bs4 import BeautifulSoup
from urllib.parse import urlparse
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from auditor.checks import (
    wordpress, wordpress_deep, seo, security, performance,
    broken_links, a11y, structured_data, legal, tech_stack,
    social, hosting, dns, content_quality,
)

console = Console()

MODULES = [
    "wordpress", "seo", "security", "performance", "broken_links",
    "a11y", "structured_data", "legal", "tech_stack", "social", "content_quality",
]


def run_audit(url: str, skip: list[str] = None) -> dict:
    skip = [s.lower() for s in (skip or [])]
    results = {}

    console.print(f"\n[bold cyan]Site Auditor[/bold cyan] → [white]{url}[/white]\n")

    # Load page
    with console.status("[bold]Seite wird geladen...[/bold]"):
        html, resp_headers, response_time_ms = _fetch(url)

    if html is None:
        console.print("[red]Fehler: Seite konnte nicht geladen werden.[/red]")
        return {}

    soup = BeautifulSoup(html, "lxml")

    # Inject meta info into headers dict for modules to use
    resp_headers["_response_time_ms"] = response_time_ms
    resp_headers["_http_version"] = "HTTP/2" if "HTTP/2" in resp_headers.get("_raw_version", "") else "HTTP/1.1"

    # WordPress detection first
    console.print("[dim]→ WordPress-Erkennung[/dim]")
    wp_result = wordpress.run(url, html, soup, resp_headers)
    results["wordpress"] = wp_result

    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console) as progress:

        # hosting + dns in parallel (no HTML needed)
        if "hosting" not in skip:
            task = progress.add_task("Hosting & DNS analysieren...", total=None)
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
                f_hosting = ex.submit(hosting.run, url, "", None, resp_headers)
                f_dns = ex.submit(dns.run, url, "", None, resp_headers)
                results["hosting"] = f_hosting.result()
                results["dns"] = f_dns.result()
            progress.remove_task(task)

        # WordPress deep (conditional)
        if wp_result.get("is_wordpress") and "wordpress_deep" not in skip:
            task = progress.add_task("WordPress-Sicherheitscheck...", total=None)
            results["wordpress_deep"] = wordpress_deep.run(url, html, soup, resp_headers)
            progress.remove_task(task)

        # Sequential modules
        sequential = [
            ("seo", seo, "SEO analysieren..."),
            ("security", security, "Security-Headers prüfen..."),
            ("performance", performance, "Performance analysieren..."),
            ("broken_links", broken_links, "Links prüfen..."),
            ("structured_data", structured_data, "Strukturierte Daten prüfen..."),
            ("legal", legal, "Rechtliche Checks..."),
            ("tech_stack", tech_stack, "Tech-Stack erkennen..."),
            ("social", social, "Social & Crawlability prüfen..."),
            ("content_quality", content_quality, "Content-Qualität prüfen..."),
        ]

        for name, module, label in sequential:
            if name in skip:
                continue
            task = progress.add_task(label, total=None)
            results[name] = module.run(url, html, soup, resp_headers)
            progress.remove_task(task)

        # a11y last (Playwright)
        if "a11y" not in skip:
            task = progress.add_task("Barrierefreiheit prüfen (Playwright)...", total=None)
            results["a11y"] = a11y.run(url, html, soup, resp_headers)
            progress.remove_task(task)

    console.print("\n[bold green]✓ Analyse abgeschlossen[/bold green]\n")
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
                    if candidate != url:
                        console.print(f"[yellow]⚠ HTTPS nicht verfügbar, weiter mit HTTP ({candidate})[/yellow]")
                    return r.text, h, elapsed
            except (httpx.ConnectError, httpx.TimeoutException):
                if attempt == 1:
                    break
    return None, {}, 0
