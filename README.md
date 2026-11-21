# Site Auditor

A comprehensive website audit tool — usable as a **CLI** and as a **Python library**. Runs 21 check modules covering security, SEO, performance, accessibility, DNS, legal compliance, HTML markup validity, and more, then generates a structured Markdown, HTML, or JSON report.

Built primarily for WordPress sites, but works on any URL.

---

## Features

| Module | What it checks |
|---|---|
| **Hosting & Server** | IP, ASN, provider, geolocation, server header leakage, Shodan |
| **DNS** | A/MX/NS/TXT records, SPF, DMARC, DKIM, DNSSEC, CAA, BIMI, MTA-STS |
| **Security** | HTTPS redirect, security headers, SSL certificate, cookie flags, SRI, mixed content |
| **WordPress** | Detection, version, theme, plugins |
| **WordPress Details** | Exposed endpoints, user enumeration, version freshness, plugin vulnerabilities, WooCommerce |
| **SEO** | Title, meta description, H1, canonical, OG tags, Twitter Cards, favicon |
| **Structured Data** | JSON-LD, microdata, schema.org field validation |
| **HTML Markup** | W3C Nu Html Checker validation (real HTML validity, not just heuristics) |
| **Performance** | Lighthouse metrics, compression, HTTP/2, cache headers, resource hints, image optimization |
| **Broken Links** | Async parallel link checking, soft-404 detection |
| **Accessibility** | axe-core (WCAG), alt texts, form labels, heading hierarchy, focus outline |
| **Legal** | Impressum, privacy policy, cookie banner, tracking scripts, third-party domains |
| **Tech Stack** | PHP version, CDN, cache layer, jQuery, page builder |
| **Social & Crawlability** | robots.txt, sitemap, hreflang, canonical, RSS/Atom feeds |
| **Content & Structure** | Word count, readability, duplicate title/H1, broken images |
| **AI Visibility** | robots.txt rules for AI crawlers (GPTBot, ClaudeBot, ...), llms.txt |
| **Contact** | Phone (tap-to-call), e-mail, contact form or link on the page |
| **Accessibility (static)** | Page language, alt texts, form labels, accessibility statement link (no browser needed) |
| **Mobile UX** | Viewport meta, horizontal scrolling at 390 px, a way to act in the first screen (call, mail, form, button), tap targets under 24 px (WCAG 2.5.8) |
| **Reviews** | Review markup, review widgets, testimonials; optional Google Places match (rating, count, phone/postcode comparison) |
| **Google Result** | Optional: how Google shows the domain for a search of its name (title, description, sitelinks) via DataForSEO |
| **Score** | Category scores (0-10), overall score, top 3 measures, effort ranges (estimates) in `results["score"]` |

---

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) — project & package manager
- Node.js (optional, for Lighthouse)

---

## Installation

```bash
git clone https://github.com/Tobeworks/Site-Auditor.git
cd Site-Auditor

uv sync --extra cli          # core + CLI (rich)
uv run playwright install chromium   # required for accessibility checks
```

Optional — install Lighthouse for full performance metrics:

```bash
npm install -g lighthouse
```

---

## CLI Usage

```bash
# Basic audit
uv run site-auditor https://tobeworks.de

# Skip slow modules
uv run site-auditor https://tobeworks.de --skip a11y,broken_links

# HTML report
uv run site-auditor https://tobeworks.de --format html

# JSON output (for further processing)
uv run site-auditor https://tobeworks.de --format json

# Add a plain-language AI summary (requires ANTHROPIC_API_KEY, needs the `ai` extra)
uv sync --extra cli --extra ai
uv run site-auditor https://tobeworks.de --summary

# Custom output directory
uv run site-auditor https://tobeworks.de --output ./my-reports

# List all available modules
uv run site-auditor --list-checks

# Show version
uv run site-auditor --version
```

Reports are saved to `./reports/` by default:
```
audit_example.com_20260512.md
```

To install `site-auditor` as a global command (available outside this repo):

```bash
uv tool install .
site-auditor https://tobeworks.de
```

---

## Library Usage

Install just the core (no `rich`, no `anthropic` — those are optional CLI/AI extras). The package is **not on PyPI** (the `site-auditor` name there belongs to an unrelated project), install it from GitHub and pin a tag:

```bash
uv add "site-auditor @ git+https://github.com/Tobeworks/Site-Auditor.git@v1.6.1"
# or: pip install "site-auditor @ git+https://github.com/Tobeworks/Site-Auditor.git@v1.6.1"
```

`run_audit()` is a **synchronous, blocking** function (it uses a sync `httpx` client and a sync Playwright wrapper internally). It never prints to the console — pass `on_progress` only if you want progress events.

```python
from auditor import run_audit, build_report

results = run_audit("https://tobeworks.de", skip=["a11y", "broken_links"])
# results is a dict: {"seo": {...}, "security": {...}, "markup": {...}, ...}

report_md = build_report("https://tobeworks.de", results, fmt="md")  # or fmt="json" / "html"
```

Optional progress callback (`on_progress(name: str, message: str)`), e.g. for your own logging:

```python
import logging
log = logging.getLogger("audit")

results = run_audit(
    "https://tobeworks.de",
    on_progress=lambda name, message: log.info("[%s] %s", name, message),
)
```

### Flask (sync)

Flask views are synchronous by default, so `run_audit()` can be called directly:

```python
from flask import Flask, jsonify, request
from auditor import run_audit

app = Flask(__name__)


@app.post("/audit")
def audit():
    url = request.json["url"]
    results = run_audit(url, skip=["a11y", "broken_links"])  # skip slow checks for a fast HTTP response
    return jsonify(results)
```

### FastAPI (async)

`run_audit()` is blocking, so hand it off to a worker thread instead of awaiting it directly — otherwise it blocks the event loop for the whole audit (often 10s+ with Playwright/a11y):

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

For long-running audits in a web context, prefer a background task queue (Celery, RQ, arq, FastAPI `BackgroundTasks`) over holding the HTTP request open — a full audit with all checks and Playwright a11y can take 20-60s+.

---

## API Keys (all optional)

| Key | Purpose |
|---|---|
| `WPSCAN_API_KEY` | WordPress plugin vulnerability checks via WPScan |
| `SHODAN_API_KEY` | Open ports and CVE detection via Shodan |
| `ANTHROPIC_API_KEY` | Plain-language AI summary (`--summary` flag / `auditor.summary.generate()`) |
| `GOOGLE_PLACES_API_KEY` | Google Places match for the Reviews check (rating, count; about 3.5 cents per domain and day) |
| `DATAFORSEO_API_KEY` | Google Result check, base64 of `email:password` (about 0.2 cents per domain and day) |

Copy `.env.example` to `.env` and fill in what you have:

```bash
cp .env.example .env
```

Or export them directly:

```bash
export WPSCAN_API_KEY=your_key
export SHODAN_API_KEY=your_key
export ANTHROPIC_API_KEY=your_key
```

Or use a config file (see below, CLI only).

---

## Config File (CLI only)

Create `.site-auditor.yml` in the project directory or your home directory (`~/.site-auditor.yml`). Local file takes precedence.

```yaml
output: ./reports
format: md
skip: []
wpscan_api_key: "your_key"
shodan_api_key: "your_key"
anthropic_api_key: "your_key"
```

CLI flags always override config file values.

---

## Scoring

`results["score"]` holds the grades. The calculation is deterministic and documented here, so a grade can be traced back to findings.

- Every category starts at **10 points**.
- Each open finding deducts points: **KRITISCH 3**, **HOCH 1.5**, **MITTEL 0.5**. Positive findings deduct nothing. A category never drops below 0.
- The overall score is the **mean of the checked categories**. Categories without a module that ran do not count.
- If a module of a category was skipped on purpose (`--skip` / `skip=[...]`), the category is capped at **9** and reported as `partial`, because an unchecked part cannot be assumed fine. The same cap applies when a browser-based module got no data (blocked page, browser error). `wordpress_deep` is exempt (it only runs on WordPress sites).
- Counted defects scale with their share: missing alt texts or form labels on at least half of the elements (and three or more) count as HOCH instead of MITTEL, three or more serious axe rules count as KRITISCH.
- Effort ranges (`effort_days`) are rough estimates per severity, not quotes.

Because skipped modules cap a category and unchecked categories are left out, a fast run with many `--skip` values gives a less complete picture, not a better grade.

---

## Report Format

Each report contains:

1. **AI Summary** *(if `--summary` used)* — plain-language overview for non-technical clients
2. **Executive Summary** — traffic-light status table for all modules
3. **Critical Issues** — cross-module list of highest severity findings
4. **Module Sections** — detailed findings per module with tables, issues, and successes

Status indicators: ✅ nur positive Findings · ⚠️ mindestens ein MITTEL-Finding · 🔴 mindestens ein HOCH- oder KRITISCH-Finding · ⚪ Modulfehler. Jedes Finding trägt eine Kennung (z.B. `SEO-04`), einen Schweregrad, einen Befund-, Wirkungs- und Lösungstext.

---

## Project Layout

```
site-auditor/
├── auditor/
│   ├── __init__.py      # public library API: run_audit, build_report, __version__
│   ├── cli.py            # argparse + Rich console — the `site-auditor` entry point
│   ├── runner.py          # run_audit() — orchestrates all checks, no console output
│   ├── report.py          # build()/save() — renders results into md/html/json
│   ├── summary.py         # optional AI plain-language summary
│   └── checks/            # one module per check, `run(url, html, soup, headers) -> dict`
├── main.py                # legacy entry point: `python main.py <url>`
└── pyproject.toml
```

Each check module returns a dict, always including a `"findings"` list of `Finding` objects (id/severity/finding/impact/solution — see `auditor/findings.py`), or an `"error"` key on failure — see any file in `auditor/checks/` for the pattern.

---

## License

MIT
