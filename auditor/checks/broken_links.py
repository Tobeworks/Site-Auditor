import asyncio
import httpx
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin

from auditor.findings import finding


async def _check_links(links: list[str]) -> tuple[list, list, list]:
    broken = []
    redirected = []
    soft_404 = []
    semaphore = asyncio.Semaphore(10)

    async def check(url):
        async with semaphore:
            try:
                async with httpx.AsyncClient(timeout=5, follow_redirects=False, headers={"User-Agent": "Mozilla/5.0"}) as client:
                    r = await client.head(url)
                    if r.status_code in range(400, 600):
                        broken.append({"url": url, "status": r.status_code})
                    elif r.status_code in range(300, 400):
                        redirected.append({"url": url, "status": r.status_code, "location": r.headers.get("location", "")})
                    elif r.status_code == 200:
                        try:
                            rg = await client.get(url, timeout=5)
                            from bs4 import BeautifulSoup as BS
                            text = BS(rg.text, "lxml").get_text()
                            words = len(text.split())
                            if words < 200:
                                soft_404.append(url)
                        except Exception:
                            pass
            except Exception:
                broken.append({"url": url, "status": 0})

    await asyncio.gather(*[check(u) for u in links])
    return broken, redirected, soft_404


def run(url: str, html: str, soup: BeautifulSoup, headers: dict) -> dict:
    try:
        findings = []
        hostname = urlparse(url).netloc

        all_links = []
        for tag in soup.find_all("a", href=True):
            href = tag.get("href", "").strip()
            if not href or href.startswith("#") or href.startswith("mailto:") or href.startswith("tel:"):
                continue
            full = urljoin(url, href)
            parsed = urlparse(full)
            if parsed.netloc == hostname and full not in all_links:
                all_links.append(full)

        total_links = len(all_links)
        to_check = all_links[:50]

        broken, redirected, soft_404 = asyncio.run(_check_links(to_check)) if to_check else ([], [], [])

        if to_check:
            if broken:
                findings.append(finding("LNK-01", "MITTEL", f"{len(broken)} defekte(r) Link(s) gefunden",
                    "Defekte interne Links verschwenden Crawl-Budget und führen Besucher ins Leere.",
                    solution="Defekte Links korrigieren oder entfernen."))
            else:
                findings.append(finding("LNK-01", "POSITIV", "Keine defekten Links gefunden",
                    "Alle geprüften internen Links sind erreichbar."))

            if soft_404:
                findings.append(finding("LNK-02", "MITTEL", f"{len(soft_404)} mögliche Soft-404-Seite(n) gefunden",
                    "Seiten mit HTTP 200 aber kaum Inhalt werden von Suchmaschinen oft trotzdem als Fehlerseite erkannt und schlecht bewertet.",
                    solution="Prüfen, ob diese Seiten echten Inhalt liefern sollten oder auf 404/410 umgestellt werden müssen."))
            else:
                findings.append(finding("LNK-02", "POSITIV", "Keine Soft-404-Verdachtsfälle unter den geprüften Links",
                    "Geprüfte Links liefern entweder Fehlercodes oder ausreichend Inhalt."))

        return {
            "total_links": total_links,
            "internal_links_checked": len(to_check),
            "broken_links": broken,
            "redirected_links": redirected,
            "soft_404_candidates": soft_404,
            "findings": findings,
        }
    except Exception as e:
        return {"error": str(e)}
