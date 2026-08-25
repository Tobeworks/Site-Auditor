# AGENTS.md - Site Auditor

Full specification for the `site-auditor` Python tool — usable as a CLI and as an importable library.

---

## Goal

A tool that takes a URL, runs a comprehensive website analysis, and produces a structured report (Markdown, HTML, or JSON). Usable two ways:

1. **CLI**: `site-auditor https://tobeworks.de` — for interactive use and scripted report generation.
2. **Library**: `from auditor import run_audit` — for embedding in another Python project (a backend service, a scheduled job, a Flask/FastAPI endpoint, ...).

Built primarily for WordPress sites, but works on any URL.

---

## Stack

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) — project, dependency, and packaging manager (replaces `pip` + `requirements.txt` + manual venvs)
- `httpx` for HTTP requests (incl. `AsyncClient` for parallel link checks)
- `beautifulsoup4` + `lxml` for HTML parsing
- `playwright` for a11y (axe-core) and optional performance metrics
- `dnspython` for DNS lookups
- `ipwhois` for ASN/hosting-provider lookup
- Lighthouse CLI (external, optional): `npm install -g lighthouse`
- `rich` (**optional**, `cli` extra) — terminal output for the CLI only, never imported by the core library
- `anthropic` (**optional**, `ai` extra) — the plain-language AI summary feature only

The core (`auditor.run_audit`, `auditor.build_report`) has **no** dependency on `rich` or `anthropic` — a pure-library install (`uv add site-auditor` without extras) never imports either.

---

## Project Structure

```
site-auditor/
├── auditor/
│   ├── __init__.py        # public library API: run_audit, build_report, __version__
│   ├── cli.py              # argparse + Rich console — the `site-auditor` CLI entry point
│   ├── runner.py            # run_audit() — orchestrates all checks, zero console output
│   ├── report.py             # build()/save() — renders results into md/html/json
│   ├── summary.py             # optional AI plain-language summary (needs `ai` extra)
│   └── checks/
│       ├── __init__.py         # ALL_CHECKS — single source of truth for available check names
│       ├── wordpress.py
│       ├── wordpress_deep.py
│       ├── seo.py
│       ├── security.py
│       ├── performance.py
│       ├── broken_links.py
│       ├── a11y.py
│       ├── structured_data.py
│       ├── markup.py           # W3C Nu Html Checker validation
│       ├── legal.py
│       ├── tech_stack.py
│       ├── social.py
│       ├── hosting.py
│       ├── dns.py
│       └── content_quality.py
├── main.py                 # legacy entry point: `python main.py <url>`, delegates to auditor.cli
├── test_markup.py            # assert-based smoke test for checks/markup.py
├── test_runner_silent.py       # assert-based smoke test for runner.run_audit()
└── pyproject.toml
```

---

## CLI Interface

```bash
uv run site-auditor https://tobeworks.de
uv run site-auditor https://tobeworks.de --output ./reports
uv run site-auditor https://tobeworks.de --skip broken_links
uv run site-auditor https://tobeworks.de --skip broken_links,a11y
uv run site-auditor https://tobeworks.de --format md
uv run site-auditor https://tobeworks.de --format json
uv run site-auditor https://tobeworks.de --format html
uv run site-auditor https://tobeworks.de --summary
uv run site-auditor --list-checks
uv run site-auditor --version
```

Once installed globally (`uv tool install .`), drop the `uv run` prefix: `site-auditor https://tobeworks.de`. `python main.py <url>` still works as a legacy alias.

Arguments:

- `url` (positional, required)
- `--output` (optional, default: `./reports`)
- `--skip` (optional, comma-separated module names)
- `--format` (optional, default: `md`, options: `md`, `json`, `html`)
- `--summary` (optional, additionally generates a plain-language AI summary; requires the `ai` extra + `ANTHROPIC_API_KEY`)
- `--list-checks` (optional, lists all available modules and exits)
- `--version` (optional, prints the tool version and exits)

**Config file:**

Optional YAML config file at `~/.site-auditor.yml` or `./.site-auditor.yml` (local file takes precedence). Supported fields:

```yaml
output: ./reports
format: md
skip: []
wpscan_api_key: "..."
shodan_api_key: "..."
anthropic_api_key: "..."
```

Env vars override the config file. CLI flags override everything.

---

## Library Interface

Public API, exported from `auditor/__init__.py`:

```python
from auditor import run_audit, build_report, __version__
```

### `run_audit(url, skip=None, on_progress=None) -> dict`

Synchronous, blocking. Runs the full check pipeline and returns a `dict` keyed by check name (`{"seo": {...}, "security": {...}, ...}`). Never prints to the console.

- `url: str` — target URL (scheme auto-prefixed with `https://` if missing is the CLI's job, not the library's — pass a full URL here)
- `skip: list[str] | None` — check names to skip (see `auditor.checks.ALL_CHECKS` for the full list)
- `on_progress: Callable[[str, str], None] | None` — optional callback, invoked as `on_progress(event_name, message)` at each pipeline stage (`"start"`, a check name, `"warning"`, `"error"`, `"done"`). Omit it entirely for silent library use.

```python
from auditor import run_audit

results = run_audit("https://tobeworks.de", skip=["a11y", "broken_links"])
```

With progress logging instead of Rich console output:

```python
import logging
log = logging.getLogger("audit")

results = run_audit(
    "https://tobeworks.de",
    on_progress=lambda name, message: log.info("[%s] %s", name, message),
)
```

### `build_report(url, results, ai_summary=None, fmt="md") -> str`

Renders a `run_audit()` result dict into a report string. `fmt` is one of `"md"`, `"json"`, `"html"`.

```python
from auditor import run_audit, build_report

results = run_audit("https://tobeworks.de")
report_json = build_report("https://tobeworks.de", results, fmt="json")
```

### Embedding in a web framework

`run_audit()` is **synchronous and blocking** (sync `httpx.Client`, sync Playwright wrapper via `asyncio.run()` internally for the a11y check). A full audit with all checks and Playwright can take 20-60s+.

**Flask** (sync views — call directly):

```python
from flask import Flask, jsonify, request
from auditor import run_audit

app = Flask(__name__)


@app.post("/audit")
def audit():
    url = request.json["url"]
    results = run_audit(url, skip=["a11y", "broken_links"])
    return jsonify(results)
```

**FastAPI** (async — offload to a thread so the event loop isn't blocked):

```python
import asyncio
from fastapi import FastAPI
from pydantic import BaseModel
from auditor import run_audit

app = FastAPI()


class AuditRequest(BaseModel):
    url: str
    skip: list[str] = []


@app.post("/audit")
async def audit(req: AuditRequest):
    results = await asyncio.to_thread(run_audit, req.url, req.skip)
    return results
```

For production web use, prefer a background task queue (Celery, RQ, arq, FastAPI `BackgroundTasks`) over holding the HTTP request open for the full audit duration.

---

## Common pattern for all check modules

Every module exports a function:

```python
def run(url: str, html: str, soup: BeautifulSoup, headers: dict) -> dict
```

On exception, every module returns:

```python
{"error": "error message as string"}
```

No check may crash the whole runner.

---

## runner.py

1. Load the page once via `httpx` (User-Agent: `Mozilla/5.0`, timeout 15s, up to 2 retries on network error or 5xx)
2. Pass HTML and headers to every module
3. Run `wordpress.py` first
4. If `is_wordpress: True`, also run `wordpress_deep.py`
5. Run `hosting.py` and `dns.py` in parallel (need no HTML, just the domain)
6. Run all other modules sequentially
7. Start Playwright only for `a11y.py`, close it afterward
8. Start the Lighthouse subprocess only for `performance.py`, if Lighthouse is available
9. Pass all results as a dict to `report.py`

`run_audit()` takes an optional `on_progress(name: str, message: str)` callback and fires it at each of the steps above — it never prints directly (see **Library Interface**). `auditor/cli.py` is the only place a Rich `Progress` spinner is wired up.

---

## report.py

- Filename: `audit_[domain]_[YYYYMMDD].md` (or `.json`/`.html` depending on `--format`)
- Location: `--output` path, default `./reports/`
- Sections in this order:

```
# Site Audit: [URL]
Erstellt: [ISO date]

## Executive Summary
[Traffic-light table of all modules]

## Kritische Issues
[All issues across all modules, sorted by severity, cross-module]

## SEO
## Content & Struktur
## Structured Data
## HTML Markup
## Social & Crawlability
## Performance
## Security
## Broken Links
## WordPress
## WordPress Details (only if WordPress detected)
## Accessibility
## Legal
## Hosting & Server
## DNS
## Tech Stack

---
*Generiert mit site-auditor*
*Dieser Report ersetzt keine rechtliche oder sicherheitstechnische Fachprüfung.*
```

Each section renders exactly once, in the order given by `module_order` in `report.py` — that list is the single source of truth for both the Executive Summary table and the section order (**do not duplicate a section's rendering code** — a past version of this file had every section appearing twice plus a `hosting`/`dns` key mix-up; that was found and fixed while building the `markup` check, see git history).

Executive Summary as a Markdown table with all modules in report order:

| Modul | Status | Issues |
|---|---|---|
| SEO | ⚠️ | 2 |
| Content & Struktur | ✅ | 0 |
| Structured Data | ⚠️ | 1 |
| HTML Markup | 🔴 | 4 |
| Social & Crawlability | ⚠️ | 1 |
| Performance | ⚠️ | 3 |
| Security | 🔴 | 5 |
| Broken Links | ✅ | 0 |
| WordPress | ✅ | 0 |
| WordPress Details | 🔴 | 4 |
| Accessibility | 🔴 | 8 |
| Legal | ⚠️ | 2 |
| Hosting & Server | ⚠️ | 1 |
| DNS | 🔴 | 3 |
| Tech Stack | ✅ | 0 |

**Per-module section format:**

Each section starts with a compact overview of the key metrics as a table or list, followed by issues as a `⚠️`/`🔴` list, positive findings as a `✅` list. No empty sections; on module error, render `⚪ Fehler: [message]`.

Traffic-light logic: 0 issues = ✅, 1-2 = ⚠️, 3+ issues or at least 1 critical = 🔴, module error = ⚪

---

## Module specs

### wordpress.py

Detection via:

- `/wp-content/` or `/wp-includes/` in the HTML
- `<meta name="generator" content="WordPress ...">` for the version
- CSS asset paths for the theme name
- Asset paths for plugin slugs
- `x-powered-by` header

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

Only runs when `wordpress.py` returns `is_wordpress: True`.

HEAD requests to:

- `/wp-login.php` — 200 = exposed
- `/xmlrpc.php` — 200 or 405 = issue
- `/readme.html` — 200 = version leakage
- `/license.txt` — 200 = version leakage
- `/wp-content/debug.log` — 200 = critical
- `/wp-cron.php` — 200 = directly reachable

GET request to:

- `/wp-json/wp/v2/users` — if 200 and JSON contains usernames, user enumeration is possible; extract and report the usernames

WP version check:

- Compare the detected version against `api.wordpress.org/core/version-check/1.7/`
- Compare detected vs. latest

Plugin vulnerability check:

- If the `WPSCAN_API_KEY` env var is set: check detected plugin slugs against the WPScan API
- Without a key: list slugs only, note in the report that the vuln check was skipped

**WooCommerce detection:**

- Check whether WooCommerce is active: `/wp-content/plugins/woocommerce/` in HTML assets, or `woocommerce` classes in the HTML
- If detected: HEAD request to `/wp-json/wc/v3/` — 200 without auth = API publicly accessible (critical)
- Extract the WooCommerce version from asset paths

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

Checks:

- `<title>` and its length (optimal: 50-60 chars)
- `<meta name="description">` and its length (optimal: 120-160 chars)
- H1: count and text. 0 = issue, more than 1 = issue
- Canonical URL via `<link rel="canonical">`
- OG tags: `og:title`, `og:description`, `og:image`, `og:type`
- OG image dimensions: `og:image:width` / `og:image:height`, recommended 1200×630px
- Twitter Cards: `twitter:card`, `twitter:title`, `twitter:description`, `twitter:image`
- `<meta name="robots">` content
- `lang` attribute on `<html>`
- Favicon: `<link rel="icon">` or `<link rel="shortcut icon">` in `<head>`, fallback HEAD request to `/favicon.ico`
- Apple touch icon: `<link rel="apple-touch-icon">`
- Web app manifest: `<link rel="manifest">` and HEAD request to `/manifest.json`

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

**HTTP header checks:**

Check the following headers, flag absence as an issue:

- `Strict-Transport-Security`: extract `max-age`, minimum 31536000, `includeSubDomains` and `preload` as bonus
- `Content-Security-Policy`
- `X-Frame-Options`
- `X-Content-Type-Options`: should be `nosniff`
- `Referrer-Policy`
- `Permissions-Policy`

**HTTPS checks:**

- Request the HTTP URL, check whether it redirects to HTTPS
- Log the full redirect chain (URL → URL → URL), not just the hop count
- Mixed content: `http://` references in `src`, `href`, `action` pointing to external domains

**Certificate:**

- Fetch the certificate via `ssl` + `socket`
- Expiry date and days remaining
- Under 30 days = warning, expired = critical

**Cookie security flags:**

- Evaluate every `Set-Cookie` header in the response
- Per cookie, check: `Secure` flag present, `HttpOnly` flag present, `SameSite` attribute set
- Missing flags on session-relevant cookie names (e.g. `PHPSESSID`, `wordpress_logged_in`, `session`) = critical

**Subresource Integrity (SRI):**

- Collect every `<script src="...">` and `<link rel="stylesheet" href="...">` pointing to external domains
- Check for an `integrity` attribute
- External resources without `integrity` = issue (supply-chain risk)

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

**Lighthouse (if available):**

Checked via `shutil.which("lighthouse")`.

Invocation:

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

Extract from the JSON: performance score, LCP, CLS, FCP, TBT, TTFB, Speed Index, top 3 opportunities with estimated time savings.

**Fallback without Lighthouse:**

- Response time via httpx
- HTML size in KB
- Total `<script>` tag count
- `<script>` without `defer`/`async` in `<head>`
- `<link rel="stylesheet">` without a `media` attribute in `<head>`

**Image optimization (always, no Lighthouse needed):**

- `<img>` without `width`/`height`
- `<img>` without `loading="lazy"` (except the first image)
- No detectable `<picture>`/`srcset` usage

**Font loading:**

- Google Fonts via `<link>` instead of `font-display: swap`
- `@import` for fonts inside `<style>` tags

**Compression & protocol:**

- Check the `Content-Encoding` header: `gzip` or `br` (Brotli) = active
- Missing compression = issue
- Read the HTTP protocol version from the httpx response (`response.http_version`): HTTP/2 or HTTP/1.1

**Cache headers:**

- Check the `Cache-Control` header (present and meaningfully populated)
- Check `ETag` and `Last-Modified`
- Missing = hint (not critical, but an optimization opportunity)

**Resource hints:**

- Check `<link rel="preconnect">` for external domains in the HTML
- Check `<link rel="preload">` for critical assets (fonts, LCP image)
- Check `<link rel="dns-prefetch">`
- External domains without preconnect (e.g. the Google Fonts origin `fonts.googleapis.com`) reported as a hint

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

- Collect every `<a href>`
- Filter internal links (same domain)
- Max 50 links, checked via `httpx.AsyncClient` with a semaphore (max. 10 parallel requests)
- 5s timeout per request
- 4xx and 5xx flagged as broken
- Redirects (3xx) listed separately
- HTTP 200 with fewer than 200 words in the body flagged as a potential soft-404

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

Evaluate: `violations` and `incomplete`.

Per violation: `id`, `impact`, WCAG mapping via `tags`, `description`, count of affected elements, one example selector from `nodes`.

Grouped by WCAG level: A, AA, AAA.

**Manual DOM checks:**

- `<img>` without `alt`, or with an empty `alt` and no `role="presentation"`
- `<input>`, `<select>`, `<textarea>` without a `<label>` or `aria-label`
- Generic `<a>` texts: "hier", "mehr", "click here", "read more", "weiter", "more", "details"
- Missing `lang` attribute on `<html>`
- Heading hierarchy: detect jumps (e.g. H1 straight to H3)
- `outline: none` or `outline: 0` inside `<style>` tags

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

- Collect every `<script type="application/ld+json">`
- Parse the JSON, extract `@type`
- Known types: `Organization`, `WebSite`, `BreadcrumbList`, `Product`, `Article`, `FAQPage`, `LocalBusiness`
- Check required fields per type:
  - `Organization`: `name`, `url`
  - `WebSite`: `name`, `url`
  - `Article`: `headline`, `author`, `datePublished`
  - `Product`: `name`, `offers`
  - `LocalBusiness`: `name`, `address`
  - Missing required fields reported as an issue

**Microdata:**

- Detect and list `itemtype` attributes in the HTML

**OG type:**

- Check `og:type` (already covered in seo.py, here only as an issue when missing)

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

Issues: no JSON-LD, JSON-LD not parseable, no `WebSite`/`Organization` schema, missing required fields, missing `og:type`, no Twitter Card.

---

### markup.py

Validates raw HTML markup against the **W3C Nu Html Checker** — the same validator behind [validator.w3.org](https://validator.w3.org/nu/). Complements `a11y.py`'s heading-hierarchy heuristic and axe-core's a11y-markup checks with an actual spec-conformance check (unclosed tags, invalid nesting, duplicate IDs, obsolete attributes, ...).

**Validation:**

- `POST` the raw `html` string to `https://validator.w3.org/nu/?out=json` with `Content-Type: text/html; charset=utf-8` via `httpx` (no extra dependency — `httpx` is already a core dep)
- Timeout 15s, same pattern as every other check: network/parse failure → `{"error": str(e)}`, never raises
- Response `messages` split by `type`: `"error"` → `errors`, `"info"`/`"warning"` → `warnings`
- `issues` gets the first 10 errors as human-readable strings (`"Zeile {line}: {message}"`), with a `"... und N weitere Markup-Fehler"` tail note if there are more

Output:

```python
{
  "errors": list[dict],       # raw Nu Html Checker error messages (message, lastLine, extract, ...)
  "warnings": list[dict],
  "error_count": int,
  "warning_count": int,
  "issues": list[str],
}
```

Note: this check sends the page's HTML to the public W3C validator service — same external-dependency trade-off as the existing WPScan/Shodan lookups in `wordpress_deep.py`/`hosting.py`. No opt-out flag; skip it per-run via `--skip markup` / `skip=["markup"]` if that's undesired for a given audit.

---

### legal.py

**Impressum:**

- Search the HTML for links with the text "Impressum", "Imprint", "Legal Notice"
- HEAD requests to `/impressum`, `/imprint`, `/legal-notice`

**Privacy policy:**

- Links with "Datenschutz", "Datenschutzerklärung", "Privacy Policy", "Privacy"
- HEAD requests to `/datenschutz`, `/privacy-policy`, `/privacy`

**Cookie banner detection:**

Search the HTML for known classes/IDs/attributes:

- `cookiebot`, `cookieconsent`, `cookie-banner`, `cmplz`, `borlabs-cookie`, `usercentrics`, `onetrust`, `didomi`

**Tracking scripts:**

Search the raw HTML for: `gtag(`, `ga(`, `fbq(`, `_paq`, `matomo`, `plausible`

**Third-party script inventory:**

- Extract every external domain from `<script src>`, `<link href>`, `<img src>`, `<iframe src>`
- Group by type (Analytics, Fonts, CDN, Social, Ads, Other) via known domains
- List in the report as a GDPR hint (which third parties are contacted)
- Known categorizations: `google-analytics.com`, `googletagmanager.com` → Analytics; `fonts.googleapis.com` → Fonts; `facebook.net`, `connect.facebook.net` → Social/Ads

Report note: possible GDPR relevance, not a legal judgment.

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

Report section carries the disclaimer: "Dieser Check ersetzt keine rechtliche Prüfung. Befunde sind technische Hinweise, keine Rechtsberatung."

---

### tech_stack.py

Detection via headers and HTML patterns:

- PHP version: `X-Powered-By` header
- CDN: `cf-ray` (Cloudflare), `x-served-by` (Fastly), Akamai headers
- Caching layer: `Via` header (Varnish, Nginx, LiteSpeed)
- jQuery version: from asset URL pattern
- Page builder: CSS classes in the HTML
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

**Canonical consistency:**

- Compare the canonical URL against the requested URL

**Hreflang:**

- Collect `<link rel="hreflang">` tags
- Check for `x-default`

**Sitemap:**

HEAD requests to: `/sitemap.xml`, `/sitemap_index.xml`, `/wp-sitemap.xml`

**robots.txt:**

- Fetch `/robots.txt`
- Check for `Disallow: /wp-admin/`
- `Disallow: /` (accidentally blocking everything) flagged critical
- Check for a sitemap reference in robots.txt

**Feed detection:**

- Search the HTML for `<link rel="alternate" type="application/rss+xml">` or `type="application/atom+xml"`
- Fallback HEAD requests to `/feed`, `/rss.xml`, `/atom.xml`, `/feed.xml`
- No feed = hint (not critical)

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

Resolves the domain's IP address and gathers hosting information. No HTML needed, runs purely on the domain.

**IP and reverse DNS:**

- Resolve the domain via `socket.gethostbyname()`
- Reverse DNS via `socket.gethostbyaddr()`
- Check IPv6 support via `socket.getaddrinfo()` with `AF_INET6`

**ASN and hosting provider:**

- Determine ASN number, ASN name, network CIDR via `ipwhois` (IPWhois lookup)
- Fallback: `ip-api.com/json/{ip}` (no API key needed, free)
- Match known hosting providers against the ASN name: Hetzner, Netcup, IONOS, Strato, OVH, AWS, Cloudflare, DigitalOcean, Contabo

**Geolocation:**

- Via `ip-api.com`: server country, city, timezone

**Server header evaluation (complements security.py):**

- `server` header: extract web server type and version
- A version in the `server` header = issue (e.g. `Apache/2.4.51` or `nginx/1.18.0`)
- `x-powered-by` with a version number = issue

**Shodan (optional):**

- If `SHODAN_API_KEY` is set: check the IP against the Shodan API
- Extract open ports and known CVEs from the Shodan data
- Without a key: note in the report that the Shodan check was skipped

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

Issues: server version visible in the header, `x-powered-by` with a version, Shodan reports critical open ports (e.g. 3306, 6379, 27017 publicly reachable).

Rendered in the report under **Hosting & Server** — see `report.py`'s `module_order`, using this module's own fields (`ip`, `hosting_provider`, `asn`, `city`/`country`, `server_header`, Shodan results). Do not confuse this with the **DNS** section, which renders `dns.py`'s output.

---

### dns.py

Full DNS analysis of the domain via `dnspython`. No HTML needed.

**Record queries:**

- `A` and `AAAA`: IP addresses
- `MX`: mail servers with priority
- `NS`: nameservers, identify the nameserver provider (Cloudflare, AWS Route53, IONOS, Hetzner)
- `TXT`: collect all TXT records
- `CNAME`: if present
- Read the TTL of all records

**SPF:**

- Check TXT records for `v=spf1`
- SPF present and syntactically valid (not fully evaluated)
- No SPF = issue

**DMARC:**

- Query the `_dmarc.[domain]` TXT record
- Check for `v=DMARC1`
- Extract the policy: `none`, `quarantine`, `reject`
- `p=none` = warning (no protection active)
- No DMARC = issue

**DKIM:**

- Check common selectors: `default._domainkey`, `google._domainkey`, `mail._domainkey`, `dkim._domainkey`
- If a TXT record is present and contains `v=DKIM1` = DKIM detected
- No DKIM found = hint (not critical, the selector may be unknown)

**DNSSEC:**

- Check the `DS` record on the domain
- Present = DNSSEC enabled

**CAA:**

- Check the `CAA` record on the domain (`dns.resolver.resolve(domain, 'CAA')`)
- Missing CAA record = hint (allows any CA to issue certificates)
- List existing CAA entries (e.g. `letsencrypt.org`, `sectigo.com`)

**BIMI:**

- Check the `default._bimi.[domain]` TXT record
- If present: extract `v=BIMI1` and the `l=` URL
- No BIMI = hint (not critical)

**MTA-STS:**

- Check the `_mta-sts.[domain]` TXT record
- HEAD request to `https://mta-sts.[domain]/.well-known/mta-sts.txt`
- No MTA-STS = hint (not critical)

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

Issues: no SPF, no DMARC, DMARC policy `none`, no DKIM found, no DNSSEC, no CAA record.

---

### content_quality.py

- Extract visible text (excluding `<nav>`, `<footer>`, `<header>`)
- Count words, under 300 = "thin content" warning
- Duplicate title/H1: when `<title>` is exactly equal to the H1
- Readability: Flesch-Kincaid approximated via average sentence length (no external packages)
- Broken images: check `<img src>` via HEAD request, max 20 images, 5s timeout, parallel via `httpx.AsyncClient`

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

## Setup & Running

```bash
uv sync --extra cli               # core + CLI (rich)
uv sync --extra cli --extra ai    # + AI summary support (anthropic)
uv run playwright install chromium   # once, for the a11y module

uv run site-auditor https://tobeworks.de
```

To install `site-auditor` as a global command:

```bash
uv tool install .
site-auditor https://tobeworks.de
```

For pure library use (embedding `run_audit`/`build_report` in another project), no extras are required:

```bash
uv add site-auditor
# or, inside another uv project's pyproject.toml, as a path/git dependency during development
```

---

## AI summary (`--summary`)

If `--summary` is set, the Claude API is called after all checks finish and a plain-language summary is generated. Requires the `ai` extra and `ANTHROPIC_API_KEY` set as an environment variable.

**Implementation (`auditor/summary.py`):**

- Compactly assemble all collected issues and metrics from the module results as text
- Send to the Claude API (model: `claude-sonnet-4-6`, prompt in German)
- Append the response as its own section `## Zusammenfassung für Laien` to the report (before the Executive Summary)
- `generate(url, results, on_progress=None)` — same callback contract as `run_audit`: no direct console output, `on_progress("warning", ...)` fires for a missing key/package instead of printing

**Prompt template:**

```
Du bist ein freundlicher Web-Experte, der einem nicht-technischen Kunden erklärt,
wie gut seine Website aufgestellt ist. Schreibe eine kurze, verständliche Zusammenfassung
(max. 300 Wörter, keine Fachbegriffe oder erkläre sie kurz) der folgenden Audit-Ergebnisse.
Beginne mit dem Gesamteindruck, nenne dann die 3 wichtigsten Probleme in einfacher Sprache
und schließe mit einer positiven Ermutigung. Verwende keine Markdown-Tabellen.

Audit-Ergebnisse:
{compressed issues and metrics from all modules}
```

**Output:** the summary is inserted as an additional block in the report:

```markdown
## Zusammenfassung für Laien

[AI-generated text in plain language]

*Dieser Text wurde automatisch von einer KI erstellt und dient nur zur Orientierung.*
```

If `ANTHROPIC_API_KEY` is not set: the section is skipped, `on_progress("warning", ...)` fires (rendered as a terminal hint via `rich` in the CLI).

---

## Environment variables

- `WPSCAN_API_KEY` (optional): WPScan Vulnerability API for plugin checks
- `SHODAN_API_KEY` (optional): Shodan lookup for open ports and CVEs
- `ANTHROPIC_API_KEY` (optional): Claude API for the `--summary` / `auditor.summary.generate()` plain-language summary

Copy `.env.example` to `.env` and fill in what you have — `auditor/cli.py` loads `.env` automatically via `python-dotenv`. Library users of `run_audit()`/`build_report()` directly are responsible for loading their own env (dotenv, container env, secrets manager, ...) before calling in.
