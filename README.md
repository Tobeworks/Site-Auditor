# Site Auditor

A comprehensive CLI tool for website analysis. Runs 14 checks covering security, SEO, performance, accessibility, DNS, legal compliance, and more — then generates a structured Markdown, HTML, or JSON report.

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
| **Performance** | Lighthouse metrics, compression, HTTP/2, cache headers, resource hints, image optimization |
| **Broken Links** | Async parallel link checking, soft-404 detection |
| **Accessibility** | axe-core (WCAG), alt texts, form labels, heading hierarchy, focus outline |
| **Legal** | Impressum, privacy policy, cookie banner, tracking scripts, third-party domains |
| **Tech Stack** | PHP version, CDN, cache layer, jQuery, page builder |
| **Social & Crawlability** | robots.txt, sitemap, hreflang, canonical, RSS/Atom feeds |
| **Content & Structure** | Word count, readability, duplicate title/H1, broken images |

---

## Requirements

- Python 3.11+
- Node.js (optional, for Lighthouse)

---

## Installation

```bash
git clone https://github.com/yourname/site-auditor.git
cd site-auditor

python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate

pip install -r requirements.txt
playwright install chromium    # required for accessibility checks
```

Optional — install Lighthouse for full performance metrics:

```bash
npm install -g lighthouse
```

---

## Usage

```bash
# Basic audit
python main.py https://example.com

# Skip slow modules
python main.py https://example.com --skip a11y,broken_links

# HTML report
python main.py https://example.com --format html

# JSON output (for further processing)
python main.py https://example.com --format json

# Add a plain-language AI summary (requires ANTHROPIC_API_KEY)
python main.py https://example.com --summary

# Custom output directory
python main.py https://example.com --output ./my-reports

# List all available modules
python main.py --list-checks

# Show version
python main.py --version
```

Reports are saved to `./reports/` by default:
```
audit_example.com_20260512.md
```

---

## API Keys (all optional)

| Key | Purpose |
|---|---|
| `WPSCAN_API_KEY` | WordPress plugin vulnerability checks via WPScan |
| `SHODAN_API_KEY` | Open ports and CVE detection via Shodan |
| `ANTHROPIC_API_KEY` | Plain-language AI summary (`--summary` flag) |

Set them as environment variables:

```bash
export WPSCAN_API_KEY=your_key
export SHODAN_API_KEY=your_key
export ANTHROPIC_API_KEY=your_key
```

Or use a config file (see below).

---

## Config File

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

## Report Format

Each report contains:

1. **AI Summary** *(if `--summary` used)* — plain-language overview for non-technical clients
2. **Executive Summary** — traffic-light status table for all modules
3. **Critical Issues** — cross-module list of highest severity findings
4. **Module Sections** — detailed findings per module with tables, issues, and successes

Status indicators: ✅ no issues · ⚠️ 1–2 issues · 🔴 3+ or critical · ⚪ module error

---

## License

MIT
