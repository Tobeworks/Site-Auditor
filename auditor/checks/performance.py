import re
import shutil
import subprocess
import json
import httpx
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin

from auditor.findings import finding

LIB_PATTERNS = {
    "jquery": re.compile(r"/jquery[.-](\d+\.\d+(?:\.\d+)?)(?:\.min)?\.js", re.I),
    "bootstrap": re.compile(r"/bootstrap[.-](\d+\.\d+(?:\.\d+)?)", re.I),
    "moment": re.compile(r"/moment[.-](\d+\.\d+(?:\.\d+)?)", re.I),
    "lodash": re.compile(r"/lodash[.-](\d+\.\d+(?:\.\d+)?)", re.I),
    "react": re.compile(r"/react[.-](\d+\.\d+(?:\.\d+)?)", re.I),
    "vue": re.compile(r"/vue[.-](\d+\.\d+(?:\.\d+)?)", re.I),
}
MODERN_IMAGE_EXTS = (".webp", ".avif")


def _collect_asset_head_info(urls: list[str]) -> list[dict]:
    """HEAD-request up to 20 asset URLs, return [{'url','bytes','cache_control','etag'}] for reachable ones."""
    info = []
    with httpx.Client(timeout=5, headers={"User-Agent": "Mozilla/5.0"}) as client:
        for u in urls[:20]:
            try:
                r = client.head(u, follow_redirects=True)
                if r.status_code < 400:
                    length = r.headers.get("content-length")
                    info.append({
                        "url": u,
                        "bytes": int(length) if length and length.isdigit() else None,
                        "cache_control": r.headers.get("cache-control"),
                        "etag": r.headers.get("etag"),
                        "last_modified": r.headers.get("last-modified"),
                    })
            except Exception:
                pass
    return info


def run(url: str, html: str, soup: BeautifulSoup, headers: dict) -> dict:
    try:
        findings = []
        hostname = urlparse(url).netloc

        # Compression & protocol
        content_encoding = headers.get("content-encoding", "")
        compression_enabled = bool(content_encoding)
        compression_type = content_encoding if compression_enabled else None

        http_version = headers.get("_http_version", "HTTP/1.1")

        # Cache headers (HTML document)
        cache_control = headers.get("cache-control")
        cache_control_present = bool(cache_control)
        etag_present = "etag" in headers

        response_time_ms = headers.get("_response_time_ms", 0)
        html_size_kb = round(len(html.encode("utf-8")) / 1024, 1)

        # Render-blocking scripts/styles in <head>
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
        all_script_srcs = [t.get("src", "") for t in soup.find_all("script", src=True)]

        # Image optimization
        images = soup.find_all("img")
        images_missing_dimensions = sum(1 for img in images if not img.get("width") or not img.get("height"))
        images_missing_lazy = sum(1 for i, img in enumerate(images) if i > 0 and img.get("loading") != "lazy")
        image_srcs = [(img.get("src", "") or "") for img in images]
        modern_count = sum(1 for s in image_srcs if s.lower().endswith(MODERN_IMAGE_EXTS))
        total_images = len(image_srcs)
        modern_image_ratio = round(modern_count / total_images, 2) if total_images else None
        uses_modern_image_formats = bool(modern_count) or soup.find("picture") is not None

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
        dns_prefetch = [tag.get("href", "") for tag in all_links if "dns-prefetch" in tag.get("rel", [])]

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

        # JS library redundancy
        versions_by_lib: dict[str, set] = {}
        for src in all_script_srcs:
            for lib, pattern in LIB_PATTERNS.items():
                m = pattern.search(src)
                if m:
                    versions_by_lib.setdefault(lib, set()).add(m.group(1))
        jquery_migrate_present = any("jquery-migrate" in s.lower() for s in all_script_srcs)
        duplicate_libs = {lib: v for lib, v in versions_by_lib.items() if len(v) > 1}

        # Icon-font detection
        icon_font_link = None
        for tag in soup.find_all("link", href=True):
            href = tag.get("href", "")
            if "font-awesome" in href.lower() or "fontawesome" in href.lower():
                icon_font_link = href if href.startswith("http") else urljoin(url, href)
                break
        icon_font_detected = icon_font_link is not None

        # Asset sample for cache-header + size checks (scripts + stylesheets, capped at 5 for cache, 20 for size ranking)
        asset_urls = []
        for tag in soup.find_all("script", src=True):
            src = tag.get("src")
            full = src if src.startswith("http") else urljoin(url, src)
            if full not in asset_urls:
                asset_urls.append(full)
        for tag in soup.find_all("link", rel="stylesheet", href=True):
            href = tag.get("href")
            full = href if href.startswith("http") else urljoin(url, href)
            if full not in asset_urls:
                asset_urls.append(full)
        for src in image_srcs:
            if not src:
                continue
            full = src if src.startswith("http") else urljoin(url, src)
            if full not in asset_urls:
                asset_urls.append(full)

        asset_info = _collect_asset_head_info(asset_urls)
        largest_assets = sorted(
            [a for a in asset_info if a["bytes"] is not None],
            key=lambda a: a["bytes"], reverse=True,
        )[:5]
        cache_sample = asset_info[:5]
        assets_missing_cache_headers = [
            a for a in cache_sample if not a["cache_control"] and not a["etag"] and not a["last_modified"]
        ]
        if icon_font_link:
            icon_font_bytes = next((a["bytes"] for a in asset_info if a["url"] == icon_font_link), None)
        else:
            icon_font_bytes = None

        # CDN detection via response headers
        cdn_header_hits = {
            "cf-ray": "Cloudflare", "x-served-by": "Fastly", "x-cache": "generisches CDN", "via": "generisches CDN",
        }
        cdn_detected = None
        for h, label in cdn_header_hits.items():
            if h in headers:
                cdn_detected = label
                break

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
                findings.append(finding("PRF-13", "MITTEL", f"Lighthouse-Auswertung fehlgeschlagen: {e}",
                    "Ohne Lighthouse-Daten fehlen Kernkennzahlen wie LCP/CLS für eine vollständige Bewertung.",
                    solution="Lighthouse-CLI-Installation und Erreichbarkeit der Seite prüfen, Audit erneut ausführen."))

        # PRF-01 Kompression
        if not compression_enabled:
            findings.append(finding("PRF-01", "MITTEL", "Keine Komprimierung aktiv (kein gzip/brotli)",
                "Unkomprimierte Übertragung verlängert Ladezeiten unnötig, besonders auf mobilen Verbindungen.",
                solution="gzip- oder Brotli-Komprimierung auf dem Webserver aktivieren."))
        else:
            findings.append(finding("PRF-01", "POSITIV", f"Komprimierung aktiv ({compression_type})",
                "Übertragene Datenmenge ist reduziert."))

        # PRF-02 Cache-Control (HTML)
        if not cache_control_present:
            findings.append(finding("PRF-02", "MITTEL", "Cache-Control-Header auf dem HTML-Dokument fehlt",
                "Browser cachen die Seite nach eigenem Ermessen — kein kontrolliertes Verhalten.",
                solution="Cache-Control gezielt setzen (z.B. no-cache für dynamische Seiten, max-age für statische)."))
        elif cache_control and "no-store" in cache_control.lower():
            findings.append(finding("PRF-02", "MITTEL", "Cache-Control: no-store auf dem HTML-Dokument",
                "no-store verhindert jegliches Caching auch für ausgeloggte Besucher — kann Ladezeiten unnötig verschlechtern (bei Login-geschützten Bereichen oft gewollt).",
                solution="Prüfen, ob no-store hier wirklich nötig ist; sonst durch ein passenderes Cache-Control ersetzen."))
        else:
            findings.append(finding("PRF-02", "POSITIV", f"Cache-Control auf dem HTML-Dokument gesetzt ({cache_control})",
                "Caching-Verhalten ist explizit kontrolliert."))

        # PRF-03 Cache-Header auf Assets
        if cache_sample:
            if assets_missing_cache_headers:
                findings.append(finding("PRF-03", "MITTEL",
                    f"{len(assets_missing_cache_headers)} von {len(cache_sample)} geprüften Assets ohne Cache-Control/ETag/Last-Modified",
                    "Browser laden diese Assets bei jedem Seitenaufruf neu, obwohl sich der Inhalt selten ändert.",
                    solution="Cache-Control mit langer max-age (+ ETag/Last-Modified) für statische Assets (CSS/JS) setzen."))
            else:
                findings.append(finding("PRF-03", "POSITIV", "Geprüfte statische Assets haben Cache-Header gesetzt",
                    "Wiederkehrende Besucher laden unveränderte Assets aus dem Browser-Cache."))

        # PRF-04 CDN-Erkennung (nur positiv, Abwesenheit ist kein Fehler)
        if cdn_detected:
            findings.append(finding("PRF-04", "POSITIV", f"CDN erkannt ({cdn_detected})",
                "Statische Assets werden über ein Content Delivery Network ausgeliefert."))

        # PRF-05 HTTP/2
        if http_version == "HTTP/1.1":
            findings.append(finding("PRF-05", "MITTEL", "HTTP/2 nicht aktiv (HTTP/1.1)",
                "HTTP/1.1 überträgt Ressourcen nacheinander statt gebündelt (Head-of-Line-Blocking) — langsamer bei vielen Requests.",
                solution="HTTP/2 auf dem Webserver/CDN aktivieren (meist ein Config-Flag, kein Code-Umbau)."))
        else:
            findings.append(finding("PRF-05", "POSITIV", f"{http_version} aktiv",
                "Ressourcen werden gebündelt/parallel übertragen."))

        # PRF-06 Render-blocking Scripts
        if render_blocking_scripts > 0:
            findings.append(finding("PRF-06", "MITTEL", f"{render_blocking_scripts} render-blockierende(s) Script(s) im <head>",
                "Blockierende Scripts verzögern das erste Rendering der Seite.",
                solution="defer oder async auf Script-Tags im <head> setzen, wo möglich."))
        else:
            findings.append(finding("PRF-06", "POSITIV", "Keine render-blockierenden Scripts im <head>",
                "Erstes Rendering wird nicht durch Scripts verzögert."))

        # PRF-07 Render-blocking Styles
        if render_blocking_styles > 0:
            findings.append(finding("PRF-07", "MITTEL", f"{render_blocking_styles} render-blockierendes Stylesheet(s) ohne media-Attribut",
                "Blockierende Stylesheets verzögern das erste Rendering der Seite.",
                solution="media-Attribut setzen oder nicht-kritisches CSS asynchron nachladen."))
        else:
            findings.append(finding("PRF-07", "POSITIV", "Keine render-blockierenden Stylesheets im <head>",
                "Erstes Rendering wird nicht durch CSS verzögert."))

        # PRF-08 Bilder ohne Dimensionen
        if images_missing_dimensions > 0:
            findings.append(finding("PRF-08", "MITTEL", f"{images_missing_dimensions} Bild(er) ohne width/height (Layout-Shift)",
                "Fehlende Dimensionen verursachen Cumulative Layout Shift (CLS) beim Laden.",
                solution="width und height (oder aspect-ratio) für alle <img>-Tags setzen."))
        elif total_images:
            findings.append(finding("PRF-08", "POSITIV", "Alle Bilder haben width/height gesetzt",
                "Kein Layout-Shift durch nachladende Bilder zu erwarten."))

        # PRF-09 Bilder ohne lazy loading
        if images_missing_lazy > 0:
            findings.append(finding("PRF-09", "MITTEL", f"{images_missing_lazy} Bild(er) ohne loading=lazy",
                "Bilder außerhalb des sichtbaren Bereichs werden unnötig früh geladen und verlängern die initiale Ladezeit.",
                solution='loading="lazy" für Bilder unterhalb des ersten Sichtbereichs setzen.'))
        elif total_images > 1:
            findings.append(finding("PRF-09", "POSITIV", "Bilder unterhalb des ersten Sichtbereichs sind lazy geladen",
                "Initiale Ladezeit wird nicht durch später sichtbare Bilder belastet."))

        # PRF-10 Font-Loading
        if font_loading_issues:
            for issue_text in font_loading_issues:
                findings.append(finding("PRF-10", "MITTEL", issue_text,
                    "Suboptimales Font-Loading verzögert oder blockiert das Rendering von Text.",
                    solution="font-display: swap verwenden und @import für Fonts vermeiden (stattdessen <link>)."))
        else:
            findings.append(finding("PRF-10", "POSITIV", "Keine Font-Loading-Probleme gefunden",
                "Web-Fonts werden ohne erkennbare Rendering-Blockade geladen."))

        # PRF-11 Preconnect-Hints
        if external_domains:
            if missing_preconnects:
                findings.append(finding("PRF-11", "MITTEL", f"Fehlende preconnect-Hints für: {', '.join(list(missing_preconnects)[:3])}",
                    "Fehlende preconnect-Hints verzögern die Verbindungsaufnahme zu externen Origins (DNS+TLS erst beim ersten Request).",
                    solution='<link rel="preconnect" href="..."> für die wichtigsten externen Origins ergänzen.'))
            else:
                findings.append(finding("PRF-11", "POSITIV", "Externe Origins sind über preconnect/dns-prefetch abgedeckt",
                    "Verbindungsaufbau zu externen Origins beginnt früher."))

        # PRF-12 Lighthouse-Score
        if lighthouse_available and performance_score is not None:
            if performance_score < 50:
                findings.append(finding("PRF-12", "HOCH", f"Lighthouse Performance-Score kritisch: {performance_score}/100",
                    "Sehr langsame wahrgenommene Ladezeit kostet Conversions und Rankings.",
                    solution="Lighthouse-Report im Detail prüfen, größte Optimierungspotenziale (siehe 'opportunities') zuerst angehen."))
            elif performance_score < 90:
                findings.append(finding("PRF-12", "MITTEL", f"Lighthouse Performance-Score verbesserungswürdig: {performance_score}/100",
                    "Es gibt messbares Optimierungspotenzial bei der Ladezeit.",
                    solution="Größte Lighthouse-Optimierungspotenziale (siehe 'opportunities') priorisiert angehen."))
            else:
                findings.append(finding("PRF-12", "POSITIV", f"Lighthouse Performance-Score gut ({performance_score}/100)",
                    "Seite lädt für die meisten Besucher spürbar schnell."))

        # PRF-14 JS-Library-Redundanz
        if duplicate_libs:
            for lib, vers in duplicate_libs.items():
                findings.append(finding("PRF-14", "HOCH", f"{lib}: mehrere Versionen gleichzeitig geladen ({', '.join(sorted(vers))})",
                    "Zwei Versionen derselben Bibliothek verdoppeln das Transfervolumen und können sich gegenseitig überschreiben (Konfliktrisiko).",
                    solution=f"Nur eine Version von {lib} einbinden, alle Referenzen auf diese Version vereinheitlichen."))
        if jquery_migrate_present:
            findings.append(finding("PRF-14", "MITTEL", "jquery-migrate eingebunden (veralteter Kompatibilitäts-Shim)",
                "jquery-migrate lädt zusätzlichen Code nur um veraltete jQuery-Aufrufe abzufangen — meist Altlast aus einem Plugin/Theme.",
                solution="Prüfen, ob jquery-migrate noch benötigt wird (welches Plugin/Theme es einbindet) und ggf. entfernen."))
        if not duplicate_libs and not jquery_migrate_present:
            findings.append(finding("PRF-14", "POSITIV", "Keine redundanten JS-Bibliotheken erkannt",
                "Keine doppelten Library-Versionen oder veralteten Compat-Shims gefunden."))

        # PRF-15 Bildformat
        if total_images:
            if modern_image_ratio < 0.5:
                findings.append(finding("PRF-15", "MITTEL", f"Nur {modern_count} von {total_images} Bildern in modernem Format (WebP/AVIF)",
                    "Ältere Formate wie JPG/PNG sind ohne Zusatztools 20-50% größer als WebP/AVIF bei gleicher Qualität.",
                    solution="Bilder nach WebP oder AVIF konvertieren (z.B. via Build-Pipeline oder Bildoptimierungs-Plugin)."))
            else:
                findings.append(finding("PRF-15", "POSITIV", f"{modern_count} von {total_images} Bildern in modernem Format (WebP/AVIF)",
                    "Bilder sind größtenteils in einem effizienten modernen Format ausgeliefert."))

        # PRF-16 Icon-Font
        if icon_font_detected:
            size_note = f", {round(icon_font_bytes / 1024)} KB" if icon_font_bytes else ""
            findings.append(finding("PRF-16", "MITTEL", f"Vollständiger Icon-Font eingebunden ({icon_font_link}{size_note})",
                "Ein kompletter Icon-Font lädt hunderte ungenutzte Icons mit — unnötiges Transfervolumen.",
                solution="Nur die tatsächlich genutzten Icons als Inline-SVG einbinden statt des vollständigen Icon-Fonts."))
        else:
            findings.append(finding("PRF-16", "POSITIV", "Kein vollständiger Icon-Font eingebunden",
                "Kein unnötiges Transfervolumen durch ungenutzte Icon-Font-Zeichen."))

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
            "modern_image_ratio": modern_image_ratio,
            "font_loading_issues": font_loading_issues,
            "compression_enabled": compression_enabled,
            "compression_type": compression_type,
            "http_version": http_version,
            "cache_control_present": cache_control_present,
            "cache_control_value": cache_control,
            "etag_present": etag_present,
            "preconnect_hints": preconnect_hints,
            "missing_preconnects": list(missing_preconnects)[:10],
            "cdn_detected": cdn_detected,
            "largest_assets": largest_assets,
            "icon_font_detected": icon_font_detected,
            "findings": findings,
        }
    except Exception as e:
        return {"error": str(e)}
