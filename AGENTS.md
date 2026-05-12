# AGENTS.md - Site Auditor

Vollständige Spezifikation für den autonomen Aufbau des `site-auditor` Python-Tools.

---

## Ziel

CLI-Tool das eine URL entgegennimmt, eine vollständige Website-Analyse durchführt und einen strukturierten Markdown-Report ausgibt. Primär für WordPress-Seiten konzipiert, funktioniert aber für beliebige URLs.

---

## Stack

- Python 3.11+
- `httpx` für HTTP-Requests (inkl. `AsyncClient` für parallele Link-Checks)
- `beautifulsoup4` für HTML-Parsing
- `playwright` für a11y (axe-core) und optional Performance
- `rich` für Terminal-Output während der Analyse
- `dnspython` für DNS-Abfragen
- `ipwhois` für ASN/Hosting-Provider-Lookup
- Lighthouse CLI (extern, optional): `npm install -g lighthouse`

---

## Projektstruktur

```
site-auditor/
├── auditor/
│   ├── __init__.py
│   ├── runner.py
│   ├── report.py
│   └── checks/
│       ├── __init__.py
│       ├── wordpress.py
│       ├── wordpress_deep.py
│       ├── seo.py
│       ├── security.py
│       ├── performance.py
│       ├── broken_links.py
│       ├── a11y.py
│       ├── structured_data.py
│       ├── legal.py
│       ├── tech_stack.py
│       ├── social.py
│       ├── hosting.py
│       ├── dns.py
│       └── content_quality.py
├── main.py
└── requirements.txt
```

---

## CLI-Interface

```
python main.py https://example.com
python main.py https://example.com --output ./reports
python main.py https://example.com --skip broken_links
python main.py https://example.com --skip broken_links,a11y
python main.py https://example.com --format md
python main.py https://example.com --format json
python main.py https://example.com --format html
python main.py https://example.com --summary
python main.py --list-checks
python main.py --version
```

Argumente:

- `url` (positional, required)
- `--output` (optional, default: `./reports`)
- `--skip` (optional, kommaseparierte Modul-Namen)
- `--format` (optional, default: `md`, Optionen: `md`, `json`, `html`)
- `--summary` (optional, generiert zusätzlich eine KI-Zusammenfassung in Laiensprache)
- `--list-checks` (optional, listet alle verfügbaren Module und beendet)
- `--version` (optional, gibt Tool-Version aus und beendet)

**Config-File:**

Optionaler YAML-Config-File unter `~/.site-auditor.yml` oder `./.site-auditor.yml` (lokale Datei hat Vorrang). Unterstützte Felder:

```yaml
output: ./reports
format: md
skip: []
wpscan_api_key: "..."
shodan_api_key: "..."
```

ENV-Variablen überschreiben Config-File. CLI-Flags überschreiben alles.

---

## Allgemeines Muster aller Check-Module

Jedes Modul exportiert eine Funktion:

```python
def run(url: str, html: str, soup: BeautifulSoup, headers: dict) -> dict
```

Bei Exception gibt jedes Modul zurück:

```python
{"error": "Fehlermeldung als String"}
```

Kein Check darf den gesamten Runner zum Absturz bringen.

---

## runner.py

1. Seite einmal laden via `httpx` (User-Agent: `Mozilla/5.0` setzen, Timeout 15s, max. 2 Retries bei Netzwerkfehler oder 5xx)
2. HTML und Headers an alle Module weitergeben
3. `wordpress.py` zuerst ausführen
4. Wenn `is_wordpress: True`, dann `wordpress_deep.py` zusätzlich ausführen
5. `hosting.py` und `dns.py` parallel ausführen (brauchen kein HTML, nur die Domain)
6. Alle anderen Module sequenziell ausführen
7. Playwright nur für `a11y.py` starten, danach schließen
8. Lighthouse-Subprocess nur für `performance.py` wenn Lighthouse verfügbar
9. Alle Ergebnisse als dict an `report.py` übergeben

---

## report.py

- Dateiname: `audit_[domain]_[YYYYMMDD].md` (bzw. `.json` oder `.html` je nach `--format`)
- Speicherort: `--output`-Pfad, default `./reports/`
- Sektionen in dieser Reihenfolge:

```
# Site Audit: [URL]
Erstellt: [ISO-Datum]

## Executive Summary
[Ampel-Tabelle aller Module]

## Kritische Issues
[Alle Issues aller Module nach Schweregrad sortiert, modulübergreifend]

## Hosting & Server
## DNS
## Security
## WordPress
## WordPress Details (nur wenn WordPress erkannt)
## SEO
## Structured Data
## Performance
## Broken Links
## Accessibility
## Legal
## Tech Stack
## Social & Crawlability
## Content & Struktur

---
*Generiert mit site-auditor*
*Dieser Report ersetzt keine rechtliche oder sicherheitstechnische Fachprüfung.*
```

Executive Summary als Markdown-Tabelle mit allen Modulen in Report-Reihenfolge:

| Modul | Status | Issues |
|---|---|---|
| Hosting & Server | ⚠️ | 1 |
| DNS | 🔴 | 3 |
| Security | 🔴 | 5 |
| WordPress | ✅ | 0 |
| WordPress Details | 🔴 | 4 |
| SEO | ⚠️ | 2 |
| Structured Data | ⚠️ | 1 |
| Performance | ⚠️ | 3 |
| Broken Links | ✅ | 0 |
| Accessibility | 🔴 | 8 |
| Legal | ⚠️ | 2 |
| Tech Stack | ✅ | 0 |
| Social & Crawlability | ⚠️ | 1 |
| Content & Struktur | ✅ | 0 |

**Sektion-Format pro Modul:**

Jede Sektion beginnt mit einer kompakten Übersicht der wichtigsten Kennzahlen als Tabelle oder Liste, danach Issues als `⚠️`- oder `🔴`-Liste, positive Befunde als `✅`-Liste. Keine leeren Sektionen, bei Modul-Error Sektion mit `⚪ Fehler: [Meldung]` ausgeben.

Ampel-Logik: 0 Issues = ✅, 1-2 = ⚠️, 3+ Issues oder mindestens 1 Critical = 🔴, Modul-Error = ⚪

---

## Modul-Specs

### wordpress.py

Erkennung via:

- `/wp-content/` oder `/wp-includes/` im HTML
- `<meta name="generator" content="WordPress ...">` für Version
- CSS-Asset-Pfade für Theme-Name
- Asset-Pfade für Plugin-Slugs
- `x-powered-by`-Header

Output:

```python
{
  "is_wordpress": bool,
  "version": str | None,
  "theme": str | None,
  "plugins": list[str]
}
```

---

### wordpress_deep.py

Nur ausführen wenn `wordpress.py` `is_wordpress: True` zurückgibt.

HEAD-Requests auf:

- `/wp-login.php` - 200 = exposed
- `/xmlrpc.php` - 200 oder 405 = Problem
- `/readme.html` - 200 = Version-Leakage
- `/license.txt` - 200 = Version-Leakage
- `/wp-content/debug.log` - 200 = kritisch
- `/wp-cron.php` - 200 = direkt erreichbar

GET-Request auf:

- `/wp-json/wp/v2/users` - wenn 200 und JSON mit Usernamen, User-Enumeration möglich, Usernamen extrahieren und melden

WP-Version-Check:

- Erkannte Version gegen `api.wordpress.org/core/version-check/1.7/` prüfen
- Vergleich: detected vs. latest

Plugin-Vulnerability-Check:

- Wenn Umgebungsvariable `WPSCAN_API_KEY` gesetzt: erkannte Plugin-Slugs gegen WPScan-API prüfen
- Ohne Key: nur Auflistung der Slugs, Hinweis im Report dass Vuln-Check nicht durchgeführt wurde

**WooCommerce-Erkennung:**

- Prüfen ob WooCommerce aktiv: `/wp-content/plugins/woocommerce/` in HTML-Assets oder `woocommerce`-Klassen im HTML
- Wenn erkannt: HEAD-Request auf `/wp-json/wc/v3/` – wenn 200 ohne Auth = API öffentlich zugänglich (Critical)
- WooCommerce-Version aus Asset-Pfaden extrahieren

Output:

```python
{
  "wp_login_exposed": bool,
  "xmlrpc_exposed": bool,
  "user_enumeration_possible": bool,
  "exposed_users": list[str],
  "readme_exposed": bool,
  "debug_log_exposed": bool,
  "wp_version_current": bool,
  "wp_version_detected": str | None,
  "wp_version_latest": str | None,
  "wpcron_exposed": bool,
  "plugins_detected": list[str],
  "plugin_vulns": list[dict],
  "woocommerce_detected": bool,
  "woocommerce_version": str | None,
  "woocommerce_api_public": bool,
  "issues": list[str]
}
```

---

### seo.py

Prüft:

- `<title>` und Länge (optimal: 50-60 Zeichen)
- `<meta name="description">` und Länge (optimal: 120-160 Zeichen)
- H1: Anzahl und Text. 0 = Issue, mehr als 1 = Issue
- Canonical URL via `<link rel="canonical">`
- OG-Tags: `og:title`, `og:description`, `og:image`, `og:type`
- OG-Image-Dimensionen: `og:image:width` / `og:image:height` prüfen, Empfehlung 1200×630px
- Twitter Cards: `twitter:card`, `twitter:title`, `twitter:description`, `twitter:image`
- `<meta name="robots">` Inhalt
- `lang`-Attribut auf `<html>`
- Favicon: `<link rel="icon">` oder `<link rel="shortcut icon">` im `<head>`, Fallback HEAD-Request auf `/favicon.ico`
- Apple Touch Icon: `<link rel="apple-touch-icon">`
- Web App Manifest: `<link rel="manifest">` und HEAD-Request auf `/manifest.json`

Output:

```python
{
  "title": str | None,
  "title_length": int,
  "meta_description": str | None,
  "meta_description_length": int,
  "h1_tags": list[str],
  "h1_count": int,
  "canonical": str | None,
  "og_title": str | None,
  "og_description": str | None,
  "og_image": str | None,
  "og_image_width": int | None,
  "og_image_height": int | None,
  "og_type": str | None,
  "twitter_card": str | None,
  "twitter_title": str | None,
  "twitter_description": str | None,
  "twitter_image": str | None,
  "robots_meta": str | None,
  "lang": str | None,
  "favicon_found": bool,
  "apple_touch_icon_found": bool,
  "web_app_manifest_found": bool,
  "issues": list[str]
}
```

---

### security.py

**HTTP-Header-Checks:**

Folgende Header prüfen und Fehlen als Issue markieren:

- `Strict-Transport-Security`: `max-age` extrahieren, Minimum 31536000, `includeSubDomains` und `preload` als Bonus
- `Content-Security-Policy`
- `X-Frame-Options`
- `X-Content-Type-Options`: Sollte `nosniff` sein
- `Referrer-Policy`
- `Permissions-Policy`

**HTTPS-Checks:**

- HTTP-URL anfragen, prüfen ob auf HTTPS redirected wird
- Vollständige Redirect-Kette loggen (URL → URL → URL), nicht nur Hop-Anzahl
- Mixed Content: `http://`-Referenzen in `src`, `href`, `action` auf externe Domains

**Zertifikat:**

- Via `ssl` + `socket` das Zertifikat abrufen
- Ablaufdatum und Restlaufzeit in Tagen
- Unter 30 Tage = Warning, abgelaufen = Critical

**Cookie Security Flags:**

- Alle `Set-Cookie`-Header aus der Response auswerten
- Pro Cookie prüfen: `Secure`-Flag vorhanden, `HttpOnly`-Flag vorhanden, `SameSite`-Attribut gesetzt
- Fehlende Flags bei Cookies mit Session-relevanten Namen (z.B. `PHPSESSID`, `wordpress_logged_in`, `session`) als Critical markieren

**Subresource Integrity (SRI):**

- Alle `<script src="...">` und `<link rel="stylesheet" href="...">` die auf externe Domains verweisen sammeln
- Prüfen ob `integrity`-Attribut vorhanden
- Externe Ressourcen ohne `integrity` = Issue (Supply-Chain-Risiko)

Output:

```python
{
  "https_redirect": bool,
  "redirect_hops": int,
  "redirect_chain": list[str],
  "hsts": bool,
  "hsts_max_age": int | None,
  "hsts_include_subdomains": bool,
  "hsts_preload": bool,
  "csp": bool,
  "x_frame_options": bool,
  "x_content_type_options": bool,
  "referrer_policy": bool,
  "permissions_policy": bool,
  "mixed_content_urls": list[str],
  "cert_valid": bool,
  "cert_expires_in_days": int | None,
  "cert_expiry_date": str | None,
  "cookies_checked": int,
  "cookies_missing_secure": list[str],
  "cookies_missing_httponly": list[str],
  "cookies_missing_samesite": list[str],
  "external_scripts_without_sri": list[str],
  "issues": list[str]
}
```

---

### performance.py

**Lighthouse (wenn verfügbar):**

Prüfung via `shutil.which("lighthouse")`.

Aufruf:

```python
subprocess.run([
    "lighthouse", url,
    "--output=json",
    "--output-path=stdout",
    "--chrome-flags=--headless --no-sandbox",
    "--quiet",
    "--only-categories=performance"
], capture_output=True)
```

Extrahieren aus JSON: Performance-Score, LCP, CLS, FCP, TBT, TTFB, Speed Index, Top-3 Opportunities mit geschätzter Zeitersparnis.

**Fallback ohne Lighthouse:**

- Response-Zeit via httpx
- HTML-Größe in KB
- Anzahl `<script>`-Tags gesamt
- `<script>` ohne `defer`/`async` im `<head>`
- `<link rel="stylesheet">` ohne `media`-Attribut im `<head>`

**Bildoptimierung (immer, kein Lighthouse nötig):**

- `<img>` ohne `width`/`height`
- `<img>` ohne `loading="lazy"` (außer erstes Bild)
- Keine `<picture>`/`srcset`-Nutzung detektierbar

**Font-Loading:**

- Google Fonts via `<link>` statt `font-display: swap`
- `@import` für Fonts in `<style>`-Tags

**Compression & Protokoll:**

- `Content-Encoding`-Header prüfen: `gzip` oder `br` (Brotli) = aktiv
- Fehlende Komprimierung = Issue
- HTTP-Protokoll-Version aus httpx-Response auslesen (`response.http_version`): HTTP/2 oder HTTP/1.1

**Cache-Headers:**

- `Cache-Control`-Header prüfen (vorhanden und sinnvoll befüllt)
- `ETag` und `Last-Modified` prüfen
- Fehlen = Hinweis (kein Critical, aber Optimierungspotential)

**Resource Hints:**

- `<link rel="preconnect">` für externe Domains im HTML prüfen
- `<link rel="preload">` für kritische Assets (Fonts, LCP-Bild) prüfen
- `<link rel="dns-prefetch">` prüfen
- Externe Domains ohne preconnect (z.B. Google Fonts Origin `fonts.googleapis.com`) als Hinweis melden

Output:

```python
{
  "lighthouse_available": bool,
  "performance_score": int | None,
  "lcp": float | None,
  "cls": float | None,
  "fcp": float | None,
  "tbt": float | None,
  "ttfb": float | None,
  "speed_index": float | None,
  "opportunities": list[dict],
  "response_time_ms": int,
  "html_size_kb": float,
  "render_blocking_scripts": int,
  "render_blocking_styles": int,
  "images_missing_dimensions": int,
  "images_missing_lazy": int,
  "uses_modern_image_formats": bool,
  "font_loading_issues": list[str],
  "compression_enabled": bool,
  "compression_type": str | None,
  "http_version": str,
  "cache_control_present": bool,
  "cache_control_value": str | None,
  "etag_present": bool,
  "preconnect_hints": list[str],
  "missing_preconnects": list[str],
  "issues": list[str]
}
```

---

### broken_links.py

- Alle `<a href>` sammeln
- Interne Links filtern (gleiche Domain)
- Max 50 Links, per `httpx.AsyncClient` mit Semaphore (max. 10 parallele Requests) prüfen
- Timeout 5s pro Request
- 4xx und 5xx als broken markieren
- Redirects (3xx) separat aufführen
- HTTP 200 mit weniger als 200 Wörtern im Body als potentielle Soft-404 markieren

Output:

```python
{
  "total_links": int,
  "internal_links_checked": int,
  "broken_links": list[{"url": str, "status": int}],
  "redirected_links": list[{"url": str, "status": int, "location": str}],
  "soft_404_candidates": list[str],
  "issues": list[str]
}
```

---

### a11y.py

**axe-core via Playwright:**

```python
await page.add_script_tag(url="https://cdnjs.cloudflare.com/ajax/libs/axe-core/4.9.1/axe.min.js")
results = await page.evaluate("axe.run()")
```

Auswerten: `violations` und `incomplete`.

Pro Violation: `id`, `impact`, `wcag`-Mapping via `tags`, `description`, Anzahl betroffener Elemente, ein Beispiel-Selector aus `nodes`.

Nach WCAG-Level gruppieren: A, AA, AAA.

**Manuelle DOM-Checks:**

- `<img>` ohne `alt` oder mit leerem `alt` ohne `role="presentation"`
- `<input>`, `<select>`, `<textarea>` ohne `<label>` oder `aria-label`
- `<a>`-Texte: "hier", "mehr", "click here", "read more", "weiter", "more", "details"
- `lang`-Attribut auf `<html>` fehlt
- Überschriften-Hierarchie: Sprünge erkennen (z.B. H1 direkt zu H3)
- `outline: none` oder `outline: 0` in `<style>`-Tags suchen

Output:

```python
{
  "violations": [
    {
      "id": str,
      "impact": str,
      "wcag": str,
      "description": str,
      "affected_elements": int,
      "example_selector": str
    }
  ],
  "incomplete": list[dict],
  "violations_count": {
    "critical": int,
    "serious": int,
    "moderate": int,
    "minor": int
  },
  "manual_checks": {
    "images_without_alt": int,
    "unlabeled_inputs": int,
    "generic_link_texts": list[str],
    "heading_hierarchy_issues": list[str],
    "focus_outline_suppressed": bool,
    "lang_attribute": str | None
  },
  "issues": list[str]
}
```

---

### structured_data.py

**JSON-LD:**

- Alle `<script type="application/ld+json">` sammeln
- JSON parsen, `@type` extrahieren
- Bekannte Typen: `Organization`, `WebSite`, `BreadcrumbList`, `Product`, `Article`, `FAQPage`, `LocalBusiness`
- Pflichtfelder pro Typ prüfen:
  - `Organization`: `name`, `url`
  - `WebSite`: `name`, `url`
  - `Article`: `headline`, `author`, `datePublished`
  - `Product`: `name`, `offers`
  - `LocalBusiness`: `name`, `address`
  - Fehlende Pflichtfelder als Issue melden

**Microdata:**

- `itemtype`-Attribute im HTML erkennen und auflisten

**OG-Type:**

- `og:type` prüfen (bereits in seo.py, hier nur als Issue wenn fehlend)

**Twitter Cards:**

- `twitter:card`, `twitter:title`, `twitter:description`, `twitter:image`

Output:

```python
{
  "json_ld": list[{"type": str, "raw": dict}],
  "json_ld_count": int,
  "json_ld_field_issues": list[str],
  "microdata_types": list[str],
  "twitter_card": str | None,
  "twitter_title": str | None,
  "issues": list[str]
}
```

Issues: kein JSON-LD, JSON-LD nicht parsebar, kein `WebSite`/`Organization` Schema, Pflichtfelder fehlen, `og:type` fehlt, keine Twitter Card.

---

### legal.py

**Impressum:**

- Links mit Text "Impressum", "Imprint", "Legal Notice" im HTML suchen
- HEAD-Request auf `/impressum`, `/imprint`, `/legal-notice`

**Datenschutz:**

- Links mit "Datenschutz", "Datenschutzerklärung", "Privacy Policy", "Privacy"
- HEAD-Request auf `/datenschutz`, `/privacy-policy`, `/privacy`

**Cookie-Banner-Erkennung:**

Suche nach bekannten Klassen/IDs/Attributen im HTML:

- `cookiebot`, `cookieconsent`, `cookie-banner`, `cmplz`, `borlabs-cookie`, `usercentrics`, `onetrust`, `didomi`

**Tracking-Scripts:**

Direkt im HTML suchen nach: `gtag(`, `ga(`, `fbq(`, `_paq`, `matomo`, `plausible`

**Third-Party Script Inventory:**

- Alle externen Domains aus `<script src>`, `<link href>`, `<img src>`, `<iframe src>` extrahieren
- Gruppieren nach Typ (Analytics, Fonts, CDN, Social, Ads, Sonstiges) anhand bekannter Domains
- Liste im Report ausgeben als DSGVO-Hinweis (welche Drittanbieter werden kontaktiert)
- Bekannte Kategorisierungen: `google-analytics.com`, `googletagmanager.com` → Analytics; `fonts.googleapis.com` → Fonts; `facebook.net`, `connect.facebook.net` → Social/Ads

Hinweis im Report: DSGVO-Relevanz möglich, kein rechtliches Urteil.

Output:

```python
{
  "impressum_found": bool,
  "impressum_url": str | None,
  "privacy_found": bool,
  "privacy_url": str | None,
  "cookie_banner_detected": bool,
  "cookie_solution": str | None,
  "tracking_in_html": list[str],
  "third_party_domains": list[{"domain": str, "category": str}],
  "issues": list[str]
}
```

Report-Sektion mit Disclaimer: "Dieser Check ersetzt keine rechtliche Prüfung. Befunde sind technische Hinweise, keine Rechtsberatung."

---

### tech_stack.py

Erkennung via Header und HTML-Patterns:

- PHP-Version: `X-Powered-By`-Header
- CDN: `cf-ray` (Cloudflare), `x-served-by` (Fastly), Akamai-Header
- Caching-Layer: `Via`-Header (Varnish, Nginx, LiteSpeed)
- jQuery-Version: aus Asset-URL-Pattern
- Page-Builder: CSS-Klassen im HTML
  - Elementor: `elementor-`
  - Divi: `et_pb_`
  - WPBakery: `vc_row`
  - Gutenberg: `wp-block-`

Output:

```python
{
  "php_version": str | None,
  "cdn": str | None,
  "cache_layer": str | None,
  "jquery_version": str | None,
  "page_builder": str | None,
  "issues": list[str]
}
```

---

### social.py

**Canonical-Konsistenz:**

- Canonical URL mit aufgerufener URL vergleichen

**Hreflang:**

- `<link rel="hreflang">` Tags sammeln
- `x-default` vorhanden prüfen

**Sitemap:**

HEAD-Requests auf: `/sitemap.xml`, `/sitemap_index.xml`, `/wp-sitemap.xml`

**Robots.txt:**

- `/robots.txt` abrufen
- `Disallow: /wp-admin/` vorhanden prüfen
- `Disallow: /` (versehentlich alles blockiert) als Critical markieren
- Sitemap-Referenz in robots.txt prüfen

**Feed-Erkennung:**

- `<link rel="alternate" type="application/rss+xml">` oder `type="application/atom+xml"` im HTML suchen
- Fallback HEAD-Requests auf `/feed`, `/rss.xml`, `/atom.xml`, `/feed.xml`
- Kein Feed = Hinweis (kein Critical)

Output:

```python
{
  "canonical_matches": bool,
  "hreflang_tags": list[dict],
  "hreflang_x_default": bool,
  "sitemap_urls": list[str],
  "robots_txt_found": bool,
  "robots_disallow_all": bool,
  "robots_wp_admin_blocked": bool,
  "robots_sitemap_referenced": bool,
  "feed_urls": list[str],
  "issues": list[str]
}
```

---

### hosting.py

IP-Adresse der Domain auflösen und Hosting-Informationen ermitteln. Kein HTML nötig, läuft rein auf der Domain.

**IP und Reverse-DNS:**

- Domain via `socket.gethostbyname()` auflösen
- Reverse-DNS via `socket.gethostbyaddr()`
- IPv6-Unterstützung prüfen via `socket.getaddrinfo()` mit `AF_INET6`

**ASN und Hosting-Provider:**

- Via `ipwhois` (IPWhois-Lookup) ASN-Nummer, ASN-Name, Netzwerk-CIDR ermitteln
- Fallback: `ip-api.com/json/{ip}` (kein API-Key nötig, kostenlos)
- Bekannte Hosting-Provider anhand ASN-Name matchen: Hetzner, Netcup, IONOS, Strato, OVH, AWS, Cloudflare, DigitalOcean, Contabo

**Geolocation:**

- Via `ip-api.com`: Land, Stadt, Timezone des Servers

**Server-Header-Auswertung (ergänzend zu security.py):**

- `server`-Header: Webserver-Typ und Version extrahieren
- Version im `server`-Header = Issue (z.B. `Apache/2.4.51` oder `nginx/1.18.0`)
- `x-powered-by` mit Versionsnummer = Issue

**Shodan (optional):**

- Wenn `SHODAN_API_KEY` gesetzt: IP gegen Shodan-API prüfen
- Offene Ports und bekannte CVEs aus Shodan-Daten extrahieren
- Ohne Key: Hinweis im Report dass Shodan-Check übersprungen wurde

Output:

```python
{
  "ip": str,
  "ipv6_supported": bool,
  "reverse_dns": str | None,
  "asn": str | None,
  "asn_name": str | None,
  "hosting_provider": str | None,
  "network_cidr": str | None,
  "country": str | None,
  "city": str | None,
  "timezone": str | None,
  "server_header": str | None,
  "server_version_exposed": bool,
  "powered_by_version_exposed": bool,
  "shodan_open_ports": list[int],
  "shodan_vulns": list[str],
  "issues": list[str]
}
```

Issues: Server-Version im Header sichtbar, `x-powered-by` mit Version, Shodan meldet kritische offene Ports (z.B. 3306, 6379, 27017 öffentlich erreichbar).

---

### dns.py

Vollständige DNS-Analyse der Domain via `dnspython`. Kein HTML nötig.

**Records abfragen:**

- `A` und `AAAA`: IP-Adressen
- `MX`: Mailserver mit Priorität
- `NS`: Nameserver, Nameserver-Provider identifizieren (Cloudflare, AWS Route53, IONOS, Hetzner)
- `TXT`: alle TXT-Records sammeln
- `CNAME`: wenn vorhanden
- TTL aller Records auslesen

**SPF:**

- TXT-Records auf `v=spf1` prüfen
- SPF vorhanden und valide (syntaktisch, nicht vollständig evaluiert)
- Kein SPF = Issue

**DMARC:**

- `_dmarc.[domain]` TXT-Record abfragen
- `v=DMARC1` prüfen
- Policy extrahieren: `none`, `quarantine`, `reject`
- `p=none` = Warning (kein Schutz aktiv)
- Kein DMARC = Issue

**DKIM:**

- Gängige Selektoren prüfen: `default._domainkey`, `google._domainkey`, `mail._domainkey`, `dkim._domainkey`
- Wenn TXT-Record vorhanden und `v=DKIM1` enthält = DKIM erkannt
- Kein DKIM gefunden = Hinweis (kein Critical, da Selector unbekannt sein kann)

**DNSSEC:**

- `DS`-Record auf der Domain prüfen
- Vorhanden = DNSSEC aktiviert

**CAA:**

- `CAA`-Record auf der Domain prüfen (`dns.resolver.resolve(domain, 'CAA')`)
- Fehlender CAA-Record = Hinweis (erlaubt beliebige CAs Zertifikate auszustellen)
- Vorhandene CAA-Einträge auflisten (z.B. `letsencrypt.org`, `sectigo.com`)

**BIMI:**

- `default._bimi.[domain]` TXT-Record prüfen
- Wenn vorhanden: `v=BIMI1` und `l=`-URL extrahieren
- Kein BIMI = Hinweis (kein Critical)

**MTA-STS:**

- `_mta-sts.[domain]` TXT-Record prüfen
- HEAD-Request auf `https://mta-sts.[domain]/.well-known/mta-sts.txt`
- Kein MTA-STS = Hinweis (kein Critical)

Output:

```python
{
  "a_records": list[str],
  "aaaa_records": list[str],
  "mx_records": list[{"host": str, "priority": int}],
  "ns_records": list[str],
  "ns_provider": str | None,
  "txt_records": list[str],
  "cname": str | None,
  "ttl_a": int | None,
  "spf_found": bool,
  "spf_record": str | None,
  "dmarc_found": bool,
  "dmarc_policy": str | None,
  "dmarc_record": str | None,
  "dkim_found": bool,
  "dkim_selector": str | None,
  "dnssec_enabled": bool,
  "caa_records": list[str],
  "bimi_found": bool,
  "bimi_logo_url": str | None,
  "mta_sts_found": bool,
  "issues": list[str]
}
```

Issues: kein SPF, kein DMARC, DMARC-Policy `none`, kein DKIM gefunden, kein DNSSEC, kein CAA-Record.

---

### content_quality.py

- Sichtbarer Text extrahieren (ohne `<nav>`, `<footer>`, `<header>`)
- Wortanzahl zählen, unter 300 = Warning "Thin Content"
- Duplicate Title/H1: wenn `<title>` exakt gleich H1
- Lesbarkeit: Flesch-Kincaid approximiert via durchschnittlicher Satzlänge (keine externen Pakete)
- Broken Images: `<img src>` per HEAD-Request prüfen, max 20 Bilder, Timeout 5s, parallel via `httpx.AsyncClient`

Output:

```python
{
  "word_count": int,
  "thin_content": bool,
  "title_equals_h1": bool,
  "avg_sentence_length": float,
  "readability_hint": str,
  "broken_images": list[{"src": str, "status": int}],
  "issues": list[str]
}
```

---

## Setup & Ausführung

```bash
python -m venv .venv
source .venv/bin/activate        # macOS/Linux
# .venv\Scripts\activate         # Windows

pip install -r requirements.txt
playwright install chromium      # einmalig für a11y-Modul

python main.py https://example.com
```

Das Tool läuft ausschließlich im aktivierten venv. Kein globales `pip install`.

---

## KI-Zusammenfassung (`--summary`)

Wenn `--summary` gesetzt ist, wird nach Abschluss aller Checks die Claude API aufgerufen und eine laienverständliche Zusammenfassung generiert. Voraussetzung: `ANTHROPIC_API_KEY` als Umgebungsvariable gesetzt.

**Implementierung (`auditor/summary.py`):**

- Alle gesammelten Issues und Kennzahlen aus den Modul-Ergebnissen kompakt als Text zusammenstellen
- An Claude API senden (Modell: `claude-sonnet-4-6`, Prompt auf Deutsch)
- Antwort als eigene Sektion `## Zusammenfassung für Laien` an den Report anhängen (vor dem Executive Summary)

**Prompt-Vorlage:**

```
Du bist ein freundlicher Web-Experte, der einem nicht-technischen Kunden erklärt,
wie gut seine Website aufgestellt ist. Schreibe eine kurze, verständliche Zusammenfassung
(max. 300 Wörter, keine Fachbegriffe oder erkläre sie kurz) der folgenden Audit-Ergebnisse.
Beginne mit dem Gesamteindruck, nenne dann die 3 wichtigsten Probleme in einfacher Sprache
und schließe mit einer positiven Ermutigung. Verwende keine Markdown-Tabellen.

Audit-Ergebnisse:
{komprimierte Issues und Kennzahlen aller Module}
```

**Output:** Die Zusammenfassung wird als zusätzlicher Block in den Report eingefügt:

```markdown
## Zusammenfassung für Laien

[KI-generierter Text in einfacher Sprache]

*Dieser Text wurde automatisch von einer KI erstellt und dient nur zur Orientierung.*
```

Wenn `ANTHROPIC_API_KEY` nicht gesetzt: Sektion wird übersprungen, Hinweis im Terminal via `rich`.

---

## Umgebungsvariablen

- `WPSCAN_API_KEY` (optional): WPScan Vulnerability API für Plugin-Checks
- `SHODAN_API_KEY` (optional): Shodan-Lookup für offene Ports und CVEs
- `ANTHROPIC_API_KEY` (optional): Claude API für `--summary` Laien-Zusammenfassung
