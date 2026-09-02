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
        elif soup.find(class_=re.compile(r"wp-block-")):
            page_builder = "Gutenberg"

        return {
            "php_version": php_version,
            "cdn": cdn,
            "cache_layer": cache_layer,
            "jquery_version": jquery_version,
            "page_builder": page_builder,
            "findings": [],
        }
    except Exception as e:
        return {"error": str(e)}
