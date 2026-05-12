import os
from rich.console import Console

console = Console()


def _build_context(url: str, results: dict) -> str:
    lines = [f"Website: {url}\n"]

    # All issues per module
    lines.append("=== GEFUNDENE PROBLEME PRO BEREICH ===")
    for module, data in results.items():
        if not isinstance(data, dict):
            continue
        issues = data.get("issues", [])
        if issues:
            lines.append(f"\n[{module.upper()}]")
            for issue in issues:
                lines.append(f"  - {issue}")

    lines.append("\n=== TECHNISCHE KENNZAHLEN ===")

    if "security" in results:
        s = results["security"]
        lines.append(f"HTTPS aktiv: {'ja' if s.get('https_redirect') else 'NEIN'}")
        lines.append(f"SSL-Zertifikat: {'gültig bis ' + str(s.get('cert_expiry_date')) if s.get('cert_valid') else 'FEHLT/UNGÜLTIG'}")
        missing = [h for h, v in [
            ("HSTS", s.get("hsts")), ("CSP", s.get("csp")),
            ("X-Frame-Options", s.get("x_frame_options")),
            ("Referrer-Policy", s.get("referrer_policy")),
        ] if not v]
        if missing:
            lines.append(f"Fehlende Sicherheits-Header: {', '.join(missing)}")

    if "seo" in results:
        s = results["seo"]
        lines.append(f"Seitentitel: '{s.get('title') or 'FEHLT'}' ({s.get('title_length', 0)} Zeichen, optimal 50-60)")
        lines.append(f"Meta-Description: {s.get('meta_description_length', 0)} Zeichen (optimal 120-160)")
        lines.append(f"H1-Tags: {s.get('h1_count', 0)}")
        lines.append(f"Canonical-Tag: {'vorhanden' if s.get('canonical') else 'FEHLT'}")
        lines.append(f"OG-Tags (Social Media Vorschau): {'vorhanden' if s.get('og_title') else 'FEHLEN'}")
        lines.append(f"Favicon: {'vorhanden' if s.get('favicon_found') else 'FEHLT'}")

    if "structured_data" in results:
        s = results["structured_data"]
        types = [i["type"] for i in s.get("json_ld", [])]
        lines.append(f"Strukturierte Daten (JSON-LD): {', '.join(types) if types else 'KEINE – Google kann die Seite nicht als Rich Result anzeigen'}")
        if s.get("json_ld_field_issues"):
            for fi in s["json_ld_field_issues"]:
                lines.append(f"  Feldproblem: {fi}")

    if "performance" in results:
        p = results["performance"]
        if p.get("performance_score") is not None:
            lines.append(f"Lighthouse Performance-Score: {p['performance_score']}/100")
        lines.append(f"Ladezeit: {p.get('response_time_ms', 0)}ms")
        lines.append(f"Komprimierung (gzip/brotli): {'aktiv' if p.get('compression_enabled') else 'FEHLT'}")
        lines.append(f"HTTP/2: {'ja' if p.get('http_version') == 'HTTP/2' else 'nein'}")
        lines.append(f"Bilder ohne lazy loading: {p.get('images_missing_lazy', 0)}")

    if "dns" in results:
        d = results["dns"]
        lines.append(f"SPF (E-Mail-Schutz): {'vorhanden' if d.get('spf_found') else 'FEHLT'}")
        lines.append(f"DMARC (E-Mail-Schutz): {'vorhanden, Policy: ' + str(d.get('dmarc_policy')) if d.get('dmarc_found') else 'FEHLT'}")
        lines.append(f"DKIM: {'vorhanden' if d.get('dkim_found') else 'nicht gefunden'}")

    if "wordpress_deep" in results:
        w = results["wordpress_deep"]
        lines.append(f"WordPress-Version aktuell: {'ja' if w.get('wp_version_current') else 'NEIN (' + str(w.get('wp_version_detected')) + ' statt ' + str(w.get('wp_version_latest')) + ')'}")
        if w.get("plugin_vulns"):
            for pv in w["plugin_vulns"]:
                lines.append(f"Plugin-Sicherheitslücken: {pv['plugin']} ({pv['count']} Schwachstellen)")
        lines.append(f"wp-login.php exponiert: {'JA' if w.get('wp_login_exposed') else 'nein'}")
        lines.append(f"User-Enumeration möglich: {'JA' if w.get('user_enumeration_possible') else 'nein'}")

    if "a11y" in results and "error" not in results["a11y"]:
        vc = results["a11y"].get("violations_count", {})
        lines.append(f"Barrierefreiheit – kritische Verstöße: {vc.get('critical', 0)}, schwerwiegend: {vc.get('serious', 0)}")

    if "legal" in results:
        l = results["legal"]
        lines.append(f"Impressum: {'vorhanden' if l.get('impressum_found') else 'FEHLT'}")
        lines.append(f"Datenschutzerklärung: {'vorhanden' if l.get('privacy_found') else 'FEHLT'}")
        lines.append(f"Cookie-Banner: {'vorhanden (' + str(l.get('cookie_solution')) + ')' if l.get('cookie_banner_detected') else 'nicht erkannt'}")
        if l.get("tracking_needs_consent"):
            lines.append(f"Consent-pflichtiges Tracking: {', '.join(l['tracking_needs_consent'])}")

    if "broken_links" in results:
        b = results["broken_links"]
        lines.append(f"Defekte Links: {len(b.get('broken_links', []))} von {b.get('internal_links_checked', 0)} geprüften")

    if "social" in results:
        s = results["social"]
        lines.append(f"robots.txt: {'vorhanden' if s.get('robots_txt_found') else 'FEHLT'}")
        lines.append(f"Sitemap: {len(s.get('sitemap_urls', []))} gefunden")

    if "content_quality" in results:
        c = results["content_quality"]
        lines.append(f"Wortanzahl: {c.get('word_count', 0)} {'(ZU WENIG – Thin Content)' if c.get('thin_content') else ''}")

    return "\n".join(lines)


def generate(url: str, results: dict) -> str | None:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        console.print("[yellow]⚠ ANTHROPIC_API_KEY nicht gesetzt – KI-Zusammenfassung übersprungen.[/yellow]")
        return None

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
    except ImportError:
        console.print("[yellow]⚠ anthropic-Paket nicht installiert – KI-Zusammenfassung übersprungen.[/yellow]")
        return None

    context = _build_context(url, results)

    prompt = f"""Du bist ein erfahrener Web-Experte und erstellst eine präzise, vollständige Zusammenfassung eines Website-Audits für einen nicht-technischen Kunden.

WICHTIG: Erwähne ALLE relevanten Probleme aus den Audit-Daten – lasse nichts weg, auch wenn es viele sind. Erkläre Fachbegriffe kurz in Klammern.

Struktur:
1. **Gesamteindruck** (2-3 Sätze)
2. **Gefundene Probleme** (alle wichtigen, nach Priorität sortiert, als Aufzählung mit kurzer Erklärung was das bedeutet und warum es wichtig ist)
3. **Was gut funktioniert** (positive Punkte)
4. **Empfehlung** (die 3 wichtigsten nächsten Schritte)

Schreibe sachlich aber verständlich. Keine leeren Floskeln, keine übertriebene Ermutigung. Alle 4 Abschnitte müssen vollständig sein – kürze lieber einzelne Punkte als einen Abschnitt wegzulassen.

{context}"""

    console.print("[dim]→ KI-Zusammenfassung wird generiert...[/dim]")

    with client.messages.stream(
        model="claude-sonnet-4-6",
        max_tokens=3600,
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        text = stream.get_final_text()

    return text
