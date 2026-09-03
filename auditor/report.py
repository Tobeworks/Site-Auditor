import json
import os
from datetime import datetime
from urllib.parse import urlparse
from auditor import __version__

SEVERITY_ICON = {"KRITISCH": "🔴", "HOCH": "🟠", "MITTEL": "⚠️", "POSITIV": "✅"}
SEVERITY_ORDER = ["KRITISCH", "HOCH", "MITTEL", "POSITIV"]


def _status(findings: list, error: bool = False) -> str:
    if error:
        return "⚪"
    severities = {f["severity"] for f in findings}
    if "KRITISCH" in severities or "HOCH" in severities:
        return "🔴"
    if "MITTEL" in severities:
        return "⚠️"
    return "✅"


def _section_header(title: str) -> str:
    return f"\n## {title}\n"


def _findings_list(findings: list) -> str:
    if not findings:
        return "✅ Keine Findings.\n"
    lines = []
    for sev in SEVERITY_ORDER:
        for f in findings:
            if f["severity"] != sev:
                continue
            lines.append(f"- {SEVERITY_ICON[sev]} **[{f['id']}]** {f['finding']}")
            if sev != "POSITIV":
                lines.append(f"  - *Wirkung:* {f['impact']}")
                lines.append(f"  - *Lösung:* {f['solution']}")
    return "\n".join(lines) + "\n"


def build(url: str, results: dict, ai_summary: str | None = None, fmt: str = "md") -> str:
    domain = urlparse(url).netloc
    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d %H:%M")

    if fmt == "json":
        return json.dumps({"url": url, "date": date_str, "results": results}, indent=2, ensure_ascii=False, default=str)

    # Collect KRITISCH/HOCH findings across modules for the critical section
    critical_findings = []
    for module, data in results.items():
        if isinstance(data, dict) and "findings" in data:
            for f in data["findings"]:
                if f["severity"] in ("KRITISCH", "HOCH"):
                    critical_findings.append((module, f))
    critical_findings.sort(key=lambda mf: 0 if mf[1]["severity"] == "KRITISCH" else 1)

    lines = []
    lines.append(f"# Site Audit: {url}")
    lines.append(f"Erstellt: {date_str}\n")

    if ai_summary:
        lines.append(ai_summary)

    lines.append("## Executive Summary\n")
    lines.append("| Modul | Status | Issues |")
    lines.append("|---|---|---|")

    module_order = [
        ("seo", "SEO"),
        ("content_quality", "Content & Struktur"),
        ("structured_data", "Structured Data"),
        ("markup", "HTML Markup"),
        ("social", "Social & Crawlability"),
        ("performance", "Performance"),
        ("security", "Security"),
        ("broken_links", "Broken Links"),
        ("wordpress", "WordPress"),
        ("wordpress_deep", "WordPress Details"),
        ("a11y", "Accessibility"),
        ("legal", "Legal"),
        ("hosting", "Hosting & Server"),
        ("dns", "DNS"),
        ("tech_stack", "Tech Stack"),
    ]

    for key, label in module_order:
        if key not in results:
            continue
        data = results[key]
        if "error" in data:
            lines.append(f"| {label} | ⚪ | - |")
        else:
            findings = data.get("findings", [])
            status = _status(findings)
            problem_count = sum(1 for f in findings if f["severity"] != "POSITIV")
            lines.append(f"| {label} | {status} | {problem_count} |")

    lines.append("")

    if critical_findings:
        lines.append("## 🔴 Kritische Issues\n")
        for module, f in critical_findings:
            lines.append(f"- {SEVERITY_ICON[f['severity']]} **[{f['id']}]** [{module}] {f['finding']}")
        lines.append("")

    # ── Sections ── (same order as module_order above)

    if "seo" in results:
        lines.append(_section_header("SEO"))
        d = results["seo"]
        if "error" in d:
            lines.append(f"⚪ Fehler: {d['error']}\n")
        else:
            lines.append("| Prüfung | Wert |")
            lines.append("|---|---|")
            lines.append(f"| Title | {d.get('title') or '❌ fehlt'} ({d.get('title_length', 0)} Zeichen) |")
            lines.append(f"| Meta Description | {(d.get('meta_description') or '❌ fehlt')[:60]}... ({d.get('meta_description_length', 0)} Zeichen) |")
            lines.append(f"| H1 | {d.get('h1_count', 0)} Tag(s) |")
            lines.append(f"| Canonical | {d.get('canonical') or '❌ fehlt'} |")
            lines.append(f"| OG-Tags | {'✅' if d.get('og_title') else '❌'} |")
            lines.append(f"| Twitter Card | {'✅' if d.get('twitter_card') else '❌'} |")
            lines.append(f"| HTML lang | {d.get('lang') or '❌ fehlt'} |")
            lines.append(f"| Favicon | {'✅' if d.get('favicon_found') else '❌'} |")
            lines.append("")
            lines.append(_findings_list(d.get("findings", [])))

    if "content_quality" in results:
        lines.append(_section_header("Content & Struktur"))
        d = results["content_quality"]
        if "error" in d:
            lines.append(f"⚪ Fehler: {d['error']}\n")
        else:
            lines.append("| Metrik | Wert |")
            lines.append("|---|---|")
            lines.append(f"| Wortanzahl | {d.get('word_count', 0)} |")
            lines.append(f"| Thin Content | {'⚠️ ja' if d.get('thin_content') else '✅ nein'} |")
            lines.append(f"| Title = H1 | {'⚠️ ja' if d.get('title_equals_h1') else '✅ nein'} |")
            lines.append(f"| Lesbarkeit | {d.get('readability_hint', '-')} |")
            lines.append(f"| Defekte Bilder | {len(d.get('broken_images', []))} |")
            lines.append("")
            lines.append(_findings_list(d.get("findings", [])))

    if "structured_data" in results:
        lines.append(_section_header("Structured Data"))
        d = results["structured_data"]
        if "error" in d:
            lines.append(f"⚪ Fehler: {d['error']}\n")
        else:
            types = [item["type"] for item in d.get("json_ld", [])]
            lines.append(f"**JSON-LD Schemas:** {', '.join(types) if types else '❌ Keine – Google kann keine Rich Results anzeigen'}\n")
            if d.get("microdata_types"):
                lines.append(f"**Microdata:** {', '.join(d['microdata_types'])}\n")
            lines.append(_findings_list(d.get("findings", [])))

    if "markup" in results:
        lines.append(_section_header("HTML Markup"))
        d = results["markup"]
        if "error" in d:
            lines.append(f"⚪ Fehler: {d['error']}\n")
        else:
            lines.append(f"**W3C-Validierung:** {d.get('error_count', 0)} Fehler, {d.get('warning_count', 0)} Warnungen\n")
            lines.append(_findings_list(d.get("findings", [])))

    if "social" in results:
        lines.append(_section_header("Social & Crawlability"))
        d = results["social"]
        if "error" in d:
            lines.append(f"⚪ Fehler: {d['error']}\n")
        else:
            lines.append("| Prüfung | Status |")
            lines.append("|---|---|")
            lines.append(f"| robots.txt | {'✅' if d.get('robots_txt_found') else '❌'} |")
            lines.append(f"| Sitemap | {', '.join(d.get('sitemap_urls', [])) or '❌ nicht gefunden'} |")
            lines.append(f"| Canonical korrekt | {'✅' if d.get('canonical_matches') else '⚠️'} |")
            lines.append(f"| Hreflang | {len(d.get('hreflang_tags', []))} Tags |")
            lines.append(f"| Feed | {', '.join(d.get('feed_urls', [])) or '-'} |")
            lines.append("")
            lines.append(_findings_list(d.get("findings", [])))

    if "performance" in results:
        lines.append(_section_header("Performance"))
        d = results["performance"]
        if "error" in d:
            lines.append(f"⚪ Fehler: {d['error']}\n")
        else:
            lines.append("| Metrik | Wert |")
            lines.append("|---|---|")
            lines.append(f"| Ladezeit | {d.get('response_time_ms', 0)}ms |")
            lines.append(f"| HTML-Größe | {d.get('html_size_kb', 0)} KB |")
            lines.append(f"| HTTP-Version | {d.get('http_version', '-')} |")
            lines.append(f"| Komprimierung | {d.get('compression_type') or '❌ keine'} |")
            lines.append(f"| Cache-Control | {'✅' if d.get('cache_control_present') else '❌'} |")
            lines.append(f"| CDN | {d.get('cdn_detected') or '-'} |")
            if d.get("performance_score") is not None:
                lines.append(f"| Lighthouse Score | {d['performance_score']}/100 |")
                lines.append(f"| LCP | {d.get('lcp', '-')}s |")
                lines.append(f"| CLS | {d.get('cls', '-')} |")
                lines.append(f"| FCP | {d.get('fcp', '-')}s |")
                lines.append(f"| TTFB | {d.get('ttfb', '-')}s |")
            lines.append("")
            if d.get("opportunities"):
                lines.append("**Top Lighthouse-Optimierungen:**")
                for opp in d["opportunities"]:
                    lines.append(f"- {opp['title']} (~{opp['savings_ms']}ms Ersparnis)")
                lines.append("")
            if d.get("largest_assets"):
                lines.append("**Größte Assets:**")
                for a in d["largest_assets"]:
                    lines.append(f"- `{a['url']}` ({round(a['bytes'] / 1024)} KB)")
                lines.append("")
            lines.append(_findings_list(d.get("findings", [])))

    if "security" in results:
        lines.append(_section_header("Security"))
        d = results["security"]
        if "error" in d:
            lines.append(f"⚪ Fehler: {d['error']}\n")
        else:
            lines.append("| Prüfung | Status |")
            lines.append("|---|---|")
            lines.append(f"| HTTPS-Redirect | {'✅' if d.get('https_redirect') else '❌'} |")
            lines.append(f"| HSTS | {'✅' if d.get('hsts') else '❌'} |")
            lines.append(f"| CSP | {'✅' if d.get('csp') else '❌'} |")
            lines.append(f"| X-Frame-Options | {'✅' if d.get('x_frame_options') else '❌'} |")
            lines.append(f"| X-Content-Type-Options | {'✅' if d.get('x_content_type_options') else '❌'} |")
            lines.append(f"| Referrer-Policy | {'✅' if d.get('referrer_policy') else '❌'} |")
            lines.append(f"| Permissions-Policy | {'✅' if d.get('permissions_policy') else '❌'} |")
            lines.append(f"| SSL-Zertifikat | {'✅ (läuft ab: ' + str(d.get('cert_expiry_date', '')) + ')' if d.get('cert_valid') else '❌'} |")
            if d.get('redirect_chain'):
                lines.append(f"| Redirect-Kette | {' → '.join(d['redirect_chain'][:4])} |")
            lines.append("")
            if d.get("external_scripts_without_sri"):
                lines.append("**Externe Ressourcen ohne SRI:**")
                for s in d["external_scripts_without_sri"][:5]:
                    lines.append(f"- `{s}`")
                lines.append("")
            lines.append(_findings_list(d.get("findings", [])))

    if "broken_links" in results:
        lines.append(_section_header("Broken Links"))
        d = results["broken_links"]
        if "error" in d:
            lines.append(f"⚪ Fehler: {d['error']}\n")
        else:
            lines.append(f"**Links gesamt:** {d.get('total_links', 0)} | **Geprüft:** {d.get('internal_links_checked', 0)}\n")
            if d.get("broken_links"):
                lines.append("**Defekte Links:**")
                for link in d["broken_links"][:10]:
                    lines.append(f"- `{link['url']}` → HTTP {link['status']}")
                lines.append("")
            if d.get("soft_404_candidates"):
                lines.append("**Mögliche Soft-404-Seiten:**")
                for u in d["soft_404_candidates"][:5]:
                    lines.append(f"- `{u}`")
                lines.append("")
            lines.append(_findings_list(d.get("findings", [])))

    if "wordpress" in results:
        lines.append(_section_header("WordPress"))
        d = results["wordpress"]
        if "error" in d:
            lines.append(f"⚪ Fehler: {d['error']}\n")
        else:
            if not d.get("is_wordpress"):
                lines.append("✅ Kein WordPress erkannt.\n")
            else:
                lines.append("| Eigenschaft | Wert |")
                lines.append("|---|---|")
                lines.append(f"| Version | {d.get('version') or 'unbekannt'} |")
                lines.append(f"| Theme | {d.get('theme') or 'unbekannt'} |")
                lines.append(f"| Plugins erkannt | {len(d.get('plugins', []))} |")
                if d.get('plugins'):
                    lines.append(f"| Plugin-Liste | {', '.join(d['plugins'][:10])} |")
            lines.append("")
            lines.append(_findings_list(d.get("findings", [])))

    if "wordpress_deep" in results:
        lines.append(_section_header("WordPress Details"))
        d = results["wordpress_deep"]
        if "error" in d:
            lines.append(f"⚪ Fehler: {d['error']}\n")
        else:
            lines.append("| Prüfung | Status |")
            lines.append("|---|---|")
            lines.append(f"| wp-login.php | {'🔴 Exponiert' if d.get('wp_login_exposed') else '✅'} |")
            lines.append(f"| xmlrpc.php | {'🔴 Exponiert' if d.get('xmlrpc_exposed') else '✅'} |")
            lines.append(f"| readme.html | {'⚠️ Sichtbar' if d.get('readme_exposed') else '✅'} |")
            lines.append(f"| debug.log | {'🔴 Kritisch' if d.get('debug_log_exposed') else '✅'} |")
            lines.append(f"| User-Enumeration | {'🔴 Möglich' if d.get('user_enumeration_possible') else '✅'} |")
            lines.append(f"| WP-Version aktuell | {'✅' if d.get('wp_version_current') else '⚠️ ' + str(d.get('wp_version_detected', '')) + ' (aktuell: ' + str(d.get('wp_version_latest', '')) + ')'} |")
            if d.get("woocommerce_detected"):
                lines.append(f"| WooCommerce | ✅ Erkannt (v{d.get('woocommerce_version') or '?'}) |")
                lines.append(f"| WC-API öffentlich | {'🔴 JA' if d.get('woocommerce_api_public') else '✅'} |")
            lines.append("")
            lines.append(_findings_list(d.get("findings", [])))

    if "a11y" in results:
        lines.append(_section_header("Accessibility"))
        d = results["a11y"]
        if "error" in d:
            lines.append(f"⚪ Fehler: {d['error']}\n")
        else:
            vc = d.get("violations_count", {})
            lines.append("| Schweregrad | Anzahl |")
            lines.append("|---|---|")
            lines.append(f"| Kritisch | {vc.get('critical', 0)} |")
            lines.append(f"| Schwerwiegend | {vc.get('serious', 0)} |")
            lines.append(f"| Mittel | {vc.get('moderate', 0)} |")
            lines.append(f"| Gering | {vc.get('minor', 0)} |")
            lines.append("")
            lines.append(_findings_list(d.get("findings", [])))

    if "legal" in results:
        lines.append(_section_header("Legal"))
        d = results["legal"]
        if "error" in d:
            lines.append(f"⚪ Fehler: {d['error']}\n")
        else:
            lines.append("| Prüfung | Status |")
            lines.append("|---|---|")
            lines.append(f"| Impressum | {'✅ ' + str(d.get('impressum_url', '')) if d.get('impressum_found') else '❌ nicht gefunden'} |")
            lines.append(f"| Datenschutz | {'✅ ' + str(d.get('privacy_url', '')) if d.get('privacy_found') else '❌ nicht gefunden'} |")
            if d.get('cookie_banner_detected'):
                cookie_row = '✅ ' + str(d.get('cookie_solution', ''))
            elif d.get('consent_required'):
                cookie_row = '❌ nicht erkannt'
            else:
                cookie_row = '✅ nicht nötig (kein Consent-pflichtiges Tracking)'
            lines.append(f"| Cookie-Banner | {cookie_row} |")
            lines.append("")
            if d.get("tracking_in_html"):
                lines.append(f"**Tracking:** {', '.join(d['tracking_in_html'])}")
                lines.append("")
            if d.get("third_party_domains"):
                lines.append("**Drittanbieter-Domains (DSGVO-relevant):**")
                for tp in d["third_party_domains"][:10]:
                    lines.append(f"- `{tp['domain']}` ({tp['category']})")
                lines.append("")
            lines.append(_findings_list(d.get("findings", [])))
            lines.append("> *Dieser Check ersetzt keine rechtliche Prüfung. Befunde sind technische Hinweise, keine Rechtsberatung.*\n")

    if "hosting" in results:
        lines.append(_section_header("Hosting & Server"))
        d = results["hosting"]
        if "error" in d:
            lines.append(f"⚪ Fehler: {d['error']}\n")
        else:
            lines.append("| Prüfung | Wert |")
            lines.append("|---|---|")
            lines.append(f"| IP | {d.get('ip', '-')} |")
            lines.append(f"| IPv6 | {'✅' if d.get('ipv6_supported') else '❌'} |")
            lines.append(f"| Provider | {d.get('hosting_provider') or d.get('asn_name') or '-'} |")
            lines.append(f"| ASN | {d.get('asn', '-')} |")
            lines.append(f"| Standort | {', '.join(filter(None, [d.get('city'), d.get('country')])) or '-'} |")
            lines.append(f"| Server-Header | {d.get('server_header') or '-'} |")
            if d.get("php_version"):
                lines.append(f"| PHP-Version | {d['php_version']}{' (EOL: ' + d['php_eol_date'] + ')' if d.get('php_eol_date') else ''} |")
            if d.get("shodan_open_ports"):
                lines.append(f"| Offene Ports (Shodan) | {', '.join(str(p) for p in d['shodan_open_ports'])} |")
            if d.get("shodan_vulns"):
                lines.append(f"| CVEs (Shodan) | {', '.join(d['shodan_vulns'])} |")
            lines.append("")
            lines.append(_findings_list(d.get("findings", [])))

    if "dns" in results:
        lines.append(_section_header("DNS"))
        d = results["dns"]
        if "error" in d:
            lines.append(f"⚪ Fehler: {d['error']}\n")
        else:
            lines.append("| Record | Wert |")
            lines.append("|---|---|")
            lines.append(f"| A | {', '.join(d.get('a_records', ['-']))} |")
            if d.get('aaaa_records'):
                lines.append(f"| AAAA | {', '.join(d['aaaa_records'])} |")
            if d.get('mx_records'):
                mx = ', '.join(f"{m['host']} (P{m['priority']})" for m in d['mx_records'])
                lines.append(f"| MX | {mx} |")
            lines.append(f"| NS-Provider | {d.get('ns_provider', '-')} |")
            lines.append(f"| SPF | {'✅' if d.get('spf_found') else '❌'} |")
            lines.append(f"| DMARC | {'✅ (' + d['dmarc_policy'] + ')' if d.get('dmarc_found') else '❌'} |")
            lines.append(f"| DKIM | {'✅ (' + d['dkim_selector'] + ')' if d.get('dkim_found') else '❌'} |")
            lines.append(f"| DNSSEC | {'✅' if d.get('dnssec_enabled') else '❌'} |")
            lines.append(f"| CAA | {'✅' if d.get('caa_records') else '❌'} |")
            lines.append(f"| BIMI | {'✅' if d.get('bimi_found') else '❌'} |")
            lines.append(f"| MTA-STS | {'✅' if d.get('mta_sts_found') else '❌'} |")
            lines.append("")
            lines.append(_findings_list(d.get("findings", [])))

    if "tech_stack" in results:
        lines.append(_section_header("Tech Stack"))
        d = results["tech_stack"]
        if "error" in d:
            lines.append(f"⚪ Fehler: {d['error']}\n")
        else:
            lines.append("| Komponente | Erkannt |")
            lines.append("|---|---|")
            lines.append(f"| PHP-Version | {d.get('php_version') or '-'} |")
            lines.append(f"| CDN | {d.get('cdn') or '-'} |")
            lines.append(f"| Cache-Layer | {d.get('cache_layer') or '-'} |")
            lines.append(f"| jQuery | {d.get('jquery_version') or '-'} |")
            lines.append(f"| Page Builder | {d.get('page_builder') or '-'} |")
            lines.append(f"| Framework | {d.get('framework') or '-'} |")
            lines.append("")
            lines.append(_findings_list(d.get("findings", [])))

    lines.append("\n---")
    lines.append(f"*Generiert mit Tobeworks Site Auditor v{__version__}*")
    lines.append("*Dieser Report ersetzt keine rechtliche oder sicherheitstechnische Fachprüfung.*")

    content = "\n".join(lines)

    if fmt == "html":
        content = _md_to_simple_html(content, url, date_str)

    return content


def _md_to_simple_html(md: str, url: str, date_str: str) -> str:
    html_lines = [
        "<!DOCTYPE html><html lang='de'><head>",
        "<meta charset='UTF-8'>",
        f"<title>Site Audit: {url}</title>",
        "<style>",
        "body{font-family:system-ui,sans-serif;max-width:900px;margin:40px auto;padding:0 20px;color:#222}",
        "h1{color:#1a1a2e}h2{color:#16213e;border-bottom:2px solid #e0e0e0;padding-bottom:6px}",
        "table{border-collapse:collapse;width:100%;margin:12px 0}",
        "td,th{border:1px solid #ddd;padding:8px 12px;text-align:left}th{background:#f5f5f5}",
        "code{background:#f0f0f0;padding:2px 5px;border-radius:3px}",
        "blockquote{border-left:3px solid #ccc;margin:0;padding:0 16px;color:#666}",
        "</style></head><body>",
    ]
    for line in md.splitlines():
        line = line.rstrip()
        if line.startswith("# "):
            html_lines.append(f"<h1>{line[2:]}</h1>")
        elif line.startswith("## "):
            html_lines.append(f"<h2>{line[3:]}</h2>")
        elif line.startswith("**") and line.endswith("**"):
            html_lines.append(f"<strong>{line[2:-2]}</strong>")
        elif line.startswith("| "):
            html_lines.append(f"<tr>{''.join(f'<td>{c.strip()}</td>' for c in line.split('|')[1:-1])}</tr>")
        elif line.startswith("|---|"):
            html_lines.append("<thead></thead><tbody>")
        elif line.startswith("- "):
            html_lines.append(f"<li>{line[2:]}</li>")
        elif line.startswith("> "):
            html_lines.append(f"<blockquote><p>{line[2:]}</p></blockquote>")
        elif line == "---":
            html_lines.append("<hr>")
        elif line:
            html_lines.append(f"<p>{line}</p>")
    html_lines.append("</body></html>")
    return "\n".join(html_lines)


def save(content: str, url: str, output_dir: str, fmt: str = "md") -> str:
    os.makedirs(output_dir, exist_ok=True)
    domain = urlparse(url).netloc.replace(":", "_")
    date = datetime.now().strftime("%Y%m%d")
    ext = fmt if fmt in ("md", "json", "html") else "md"
    filename = f"audit_{domain}_{date}.{ext}"
    path = os.path.join(output_dir, filename)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path
