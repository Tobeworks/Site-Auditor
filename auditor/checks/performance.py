import shutil
import subprocess
import json
import time
import httpx
from bs4 import BeautifulSoup
from urllib.parse import urlparse


def run(url: str, html: str, soup: BeautifulSoup, headers: dict) -> dict:
    try:
        issues = []
        hostname = urlparse(url).netloc

        # Compression & protocol
        content_encoding = headers.get("content-encoding", "")
        compression_enabled = bool(content_encoding)
        compression_type = content_encoding if compression_enabled else None

        http_version = headers.get("_http_version", "HTTP/1.1")

        # Cache headers
        cache_control = headers.get("cache-control")
        cache_control_present = bool(cache_control)
        etag_present = "etag" in headers

        # Response time (approximated from runner, stored in headers dict as meta)
        response_time_ms = headers.get("_response_time_ms", 0)

        # HTML size
        html_size_kb = round(len(html.encode("utf-8")) / 1024, 1)

        # Render-blocking scripts in <head>
        head = soup.find("head")
        render_blocking_scripts = 0
        render_blocking_styles = 0
        if head:
            for tag in head.find_all("script", src=True):
                if not tag.get("defer") and not tag.get("async"):
                    render_blocking_scripts += 1
            for tag in head.find_all("link", rel="stylesheet"):
                if not tag.get("media"):
                    render_blocking_styles += 1

        # Image optimization
        images = soup.find_all("img")
        images_missing_dimensions = sum(1 for img in images if not img.get("width") or not img.get("height"))
        images_missing_lazy = sum(1 for i, img in enumerate(images) if i > 0 and img.get("loading") != "lazy")
        uses_modern_image_formats = any(
            (img.get("src", "") or "").lower().endswith((".webp", ".avif"))
            or soup.find("picture")
            for img in images
        )

        # Font loading issues
        font_loading_issues = []
        for style in soup.find_all("style"):
            if "@import" in style.get_text() and "font" in style.get_text().lower():
                font_loading_issues.append("@import für Fonts in <style>-Tag gefunden (blockierend)")
                break
        google_font_links = [
            tag for tag in soup.find_all("link", href=True)
            if "fonts.googleapis.com" in tag.get("href", "")
        ]
        if google_font_links:
            has_swap = any("swap" in tag.get("href", "") for tag in google_font_links)
            if not has_swap:
                font_loading_issues.append("Google Fonts ohne font-display:swap eingebunden")

        # Resource hints
        all_links = soup.find_all("link", rel=True)
        preconnect_hints = [tag.get("href", "") for tag in all_links if "preconnect" in tag.get("rel", [])]
        preload_hints = [tag.get("href", "") for tag in all_links if "preload" in tag.get("rel", [])]
        dns_prefetch = [tag.get("href", "") for tag in all_links if "dns-prefetch" in tag.get("rel", [])]

        # Detect external domains that should have preconnect
        missing_preconnects = []
        external_domains = set()
        for tag in soup.find_all(["script", "link", "img"], src=True):
            src = tag.get("src", "") or tag.get("href", "")
            if src.startswith("http") and hostname not in src:
                parsed = urlparse(src)
                external_domains.add(f"{parsed.scheme}://{parsed.netloc}")
        for tag in soup.find_all("link", href=True):
            href = tag.get("href", "")
            if href.startswith("http") and hostname not in href:
                parsed = urlparse(href)
                external_domains.add(f"{parsed.scheme}://{parsed.netloc}")
        for domain in external_domains:
            if domain not in preconnect_hints and domain not in dns_prefetch:
                missing_preconnects.append(domain)

        # Lighthouse
        lighthouse_available = bool(shutil.which("lighthouse"))
        performance_score = lcp = cls = fcp = tbt = ttfb = speed_index = None
        opportunities = []

        if lighthouse_available:
            try:
                proc = subprocess.run(
                    [
                        "lighthouse", url,
                        "--output=json",
                        "--output-path=stdout",
                        "--chrome-flags=--headless --no-sandbox",
                        "--quiet",
                        "--only-categories=performance",
                    ],
                    capture_output=True,
                    timeout=120,
                )
                data = json.loads(proc.stdout)
                cats = data.get("categories", {})
                performance_score = int((cats.get("performance", {}).get("score") or 0) * 100)
                audits = data.get("audits", {})

                def ms(key):
                    v = audits.get(key, {}).get("numericValue")
                    return round(v / 1000, 2) if v else None

                lcp = ms("largest-contentful-paint")
                cls_val = audits.get("cumulative-layout-shift", {}).get("numericValue")
                cls = round(cls_val, 3) if cls_val is not None else None
                fcp = ms("first-contentful-paint")
                tbt_val = audits.get("total-blocking-time", {}).get("numericValue")
                tbt = round(tbt_val) if tbt_val is not None else None
                ttfb = ms("server-response-time")
                si = audits.get("speed-index", {}).get("numericValue")
                speed_index = round(si / 1000, 2) if si else None

                for audit_id, audit in audits.items():
                    if audit.get("score") is not None and audit["score"] < 0.9 and audit.get("details", {}).get("overallSavingsMs"):
                        opportunities.append({
                            "id": audit_id,
                            "title": audit.get("title", ""),
                            "savings_ms": round(audit["details"]["overallSavingsMs"]),
                        })
                opportunities = sorted(opportunities, key=lambda x: x["savings_ms"], reverse=True)[:3]

            except Exception as e:
                issues.append(f"Lighthouse-Auswertung fehlgeschlagen: {e}")

        # Build issues
        if not compression_enabled:
            issues.append("Keine Komprimierung aktiv (kein gzip/brotli)")
        if not cache_control_present:
            issues.append("Cache-Control-Header fehlt")
        if http_version == "HTTP/1.1":
            issues.append("HTTP/2 nicht aktiv")
        if render_blocking_scripts > 0:
            issues.append(f"{render_blocking_scripts} render-blockierende Script(s) im <head>")
        if render_blocking_styles > 0:
            issues.append(f"{render_blocking_styles} render-blockierendes Stylesheet(s) ohne media-Attribut")
        if images_missing_dimensions > 0:
            issues.append(f"{images_missing_dimensions} Bild(er) ohne width/height (Layout-Shift)")
        if images_missing_lazy > 0:
            issues.append(f"{images_missing_lazy} Bild(er) ohne loading=lazy")
        issues.extend(font_loading_issues)
        if missing_preconnects:
            issues.append(f"Fehlende preconnect-Hints für: {', '.join(list(missing_preconnects)[:3])}")
        if lighthouse_available and performance_score is not None and performance_score < 50:
            issues.append(f"Lighthouse Performance-Score kritisch: {performance_score}/100")
        elif lighthouse_available and performance_score is not None and performance_score < 90:
            issues.append(f"Lighthouse Performance-Score verbesserungswürdig: {performance_score}/100")

        return {
            "lighthouse_available": lighthouse_available,
            "performance_score": performance_score,
            "lcp": lcp,
            "cls": cls,
            "fcp": fcp,
            "tbt": tbt,
            "ttfb": ttfb,
            "speed_index": speed_index,
            "opportunities": opportunities,
            "response_time_ms": response_time_ms,
            "html_size_kb": html_size_kb,
            "render_blocking_scripts": render_blocking_scripts,
            "render_blocking_styles": render_blocking_styles,
            "images_missing_dimensions": images_missing_dimensions,
            "images_missing_lazy": images_missing_lazy,
            "uses_modern_image_formats": uses_modern_image_formats,
            "font_loading_issues": font_loading_issues,
            "compression_enabled": compression_enabled,
            "compression_type": compression_type,
            "http_version": http_version,
            "cache_control_present": cache_control_present,
            "cache_control_value": cache_control,
            "etag_present": etag_present,
            "preconnect_hints": preconnect_hints,
            "missing_preconnects": list(missing_preconnects)[:10],
            "issues": issues,
        }
    except Exception as e:
        return {"error": str(e)}
