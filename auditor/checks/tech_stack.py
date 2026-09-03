import re
from bs4 import BeautifulSoup


def run(url: str, html: str, soup: BeautifulSoup, headers: dict) -> dict:
    try:
        # ponytail: PHP-version exposure is judged (security + EOL) in hosting.py's
        # HST-02/HST-04 — this module stays purely descriptive, no duplicate finding here.
        php_version = None
        powered_by = headers.get("x-powered-by", "")
        m = re.search(r"PHP/([\d.]+)", powered_by)
        if m:
            php_version = m.group(1)

        cdn = None
        if "cf-ray" in headers:
            cdn = "Cloudflare"
        elif "x-served-by" in headers and "cache" in headers.get("x-served-by", "").lower():
            cdn = "Fastly"
        elif "x-akamai-transformed" in headers or "akamai" in headers.get("server", "").lower():
            cdn = "Akamai"

        cache_layer = None
        via = headers.get("via", "").lower()
        server = headers.get("server", "").lower()
        if "varnish" in via or "varnish" in server:
            cache_layer = "Varnish"
        elif "nginx" in via:
            cache_layer = "Nginx"
        elif "litespeed" in server:
            cache_layer = "LiteSpeed"

        jquery_version = None
        for tag in soup.find_all("script", src=True):
            src = tag.get("src", "")
            m = re.search(r"jquery[.-]([\d.]+)(\.min)?\.js", src, re.IGNORECASE)
            if m:
                jquery_version = m.group(1)
                break

        page_builder = None
        if soup.find(class_=re.compile(r"elementor-")):
            page_builder = "Elementor"
        elif soup.find(class_=re.compile(r"et_pb_")):
            page_builder = "Divi"
        elif soup.find(class_=re.compile(r"vc_row")):
            page_builder = "WPBakery"
        elif soup.find(class_=re.compile(r"brxe-")):
            page_builder = "Bricks Builder"
        elif soup.find(class_=re.compile(r"wp-block-")):
            page_builder = "Gutenberg"

        # JS meta-framework / site-builder detection — independent of page_builder
        # above (that's WordPress-specific; a site can run neither, either, or in
        # rare headless setups both).
        def _has_asset_path(substring):
            for tag in soup.find_all(["script", "link"]):
                src = tag.get("src") or tag.get("href") or ""
                if substring in src:
                    return True
            return False

        generator_tag = soup.find("meta", attrs={"name": "generator"})
        generator = (generator_tag.get("content", "") if generator_tag else "").lower()

        framework = None
        if "astro" in generator or soup.find("astro-island") or _has_asset_path("/_astro/"):
            framework = "Astro"
        elif soup.find(id="__next") or soup.find("script", id="__NEXT_DATA__") or _has_asset_path("/_next/"):
            framework = "Next.js"
        elif soup.find(id="__nuxt") or soup.find(id="__layout") or _has_asset_path("/_nuxt/"):
            framework = "Nuxt"
        elif "wix.com" in generator or soup.find(class_=re.compile(r"^wix-")):
            framework = "Wix"

        return {
            "php_version": php_version,
            "cdn": cdn,
            "cache_layer": cache_layer,
            "jquery_version": jquery_version,
            "page_builder": page_builder,
            "framework": framework,
            "findings": [],
        }
    except Exception as e:
        return {"error": str(e)}
