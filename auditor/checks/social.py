import httpx
from bs4 import BeautifulSoup
from urllib.parse import urlparse


def run(url: str, html: str, soup: BeautifulSoup, headers: dict) -> dict:
    try:
        issues = []
        base = f"{urlparse(url).scheme}://{urlparse(url).netloc}"

        # Canonical consistency
        canonical_tag = soup.find("link", attrs={"rel": "canonical"})
        canonical = canonical_tag.get("href") if canonical_tag else None
        canonical_matches = canonical == url if canonical else False

        # Hreflang
        hreflang_tags = []
        for tag in soup.find_all("link", rel="alternate"):
            lang = tag.get("hreflang")
            if lang:
                hreflang_tags.append({"lang": lang, "href": tag.get("href", "")})
        hreflang_x_default = any(t["lang"] == "x-default" for t in hreflang_tags)

        # Sitemap
        sitemap_urls = []
        with httpx.Client(timeout=8, headers={"User-Agent": "Mozilla/5.0"}) as client:
            for path in ["/sitemap.xml", "/sitemap_index.xml", "/wp-sitemap.xml"]:
                try:
                    r = client.head(f"{base}{path}")
                    if r.status_code in (200, 301, 302):
                        sitemap_urls.append(f"{base}{path}")
                except Exception:
                    pass

            # Robots.txt
            robots_txt_found = False
            robots_disallow_all = False
            robots_wp_admin_blocked = False
            robots_sitemap_referenced = False
            try:
                r = client.get(f"{base}/robots.txt")
                if r.status_code == 200:
                    robots_txt_found = True
                    robots_content = r.text.lower()
                    if "disallow: /" in robots_content and "disallow: /wp" not in robots_content:
                        # Check if it's a bare "Disallow: /"
                        for line in r.text.splitlines():
                            stripped = line.strip()
                            if stripped.lower() == "disallow: /":
                                robots_disallow_all = True
                    robots_wp_admin_blocked = "disallow: /wp-admin" in robots_content
                    robots_sitemap_referenced = "sitemap:" in robots_content
            except Exception:
                pass

            # Feed detection
            feed_urls = []
            for tag in soup.find_all("link", rel="alternate"):
                link_type = tag.get("type", "")
                if "rss" in link_type or "atom" in link_type:
                    href = tag.get("href", "")
                    if href:
                        feed_urls.append(href)
            if not feed_urls:
                for path in ["/feed", "/rss.xml", "/atom.xml", "/feed.xml"]:
                    try:
                        r = client.head(f"{base}{path}")
                        if r.status_code == 200:
                            feed_urls.append(f"{base}{path}")
                    except Exception:
                        pass

        # Issues
        if not robots_txt_found:
            issues.append("robots.txt nicht gefunden")
        if robots_disallow_all:
            issues.append("🔴 KRITISCH: robots.txt blockiert alle Crawler (Disallow: /)")
        if not robots_wp_admin_blocked and "/wp-content/" in html:
            issues.append("/wp-admin/ nicht in robots.txt blockiert")
        if not sitemap_urls:
            issues.append("Keine Sitemap gefunden")
        if not robots_sitemap_referenced and sitemap_urls:
            issues.append("Sitemap nicht in robots.txt referenziert")
        if canonical and not canonical_matches:
            issues.append(f"Canonical-URL stimmt nicht mit aufgerufener URL überein")

        return {
            "canonical_matches": canonical_matches,
            "hreflang_tags": hreflang_tags,
            "hreflang_x_default": hreflang_x_default,
            "sitemap_urls": sitemap_urls,
            "robots_txt_found": robots_txt_found,
            "robots_disallow_all": robots_disallow_all,
            "robots_wp_admin_blocked": robots_wp_admin_blocked,
            "robots_sitemap_referenced": robots_sitemap_referenced,
            "feed_urls": feed_urls,
            "issues": issues,
        }
    except Exception as e:
        return {"error": str(e)}
