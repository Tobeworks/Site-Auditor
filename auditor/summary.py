import os
from rich.console import Console

console = Console()


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

    # Collect all issues
    all_issues = []
    for module, data in results.items():
        if isinstance(data, dict) and "issues" in data:
            for issue in data["issues"]:
                all_issues.append(f"[{module}] {issue}")

    # Key metrics
    metrics = []
    if "seo" in results:
        s = results["seo"]
        metrics.append(f"Title: '{s.get('title', 'fehlt')}' ({s.get('title_length', 0)} Zeichen)")
    if "performance" in results:
        p = results["performance"]
        if p.get("performance_score") is not None:
            metrics.append(f"Lighthouse Performance: {p['performance_score']}/100")
        metrics.append(f"Ladezeit: {p.get('response_time_ms', 0)}ms")
    if "security" in results:
        sec = results["security"]
        metrics.append(f"HTTPS: {'ja' if sec.get('https_redirect') else 'nein'}")
    if "a11y" in results:
        vc = results["a11y"].get("violations_count", {})
        metrics.append(f"Barrierefreiheit: {vc.get('critical', 0)} kritische, {vc.get('serious', 0)} schwerwiegende Verstöße")
    if "content_quality" in results:
        cq = results["content_quality"]
        metrics.append(f"Wortanzahl: {cq.get('word_count', 0)}")

    issues_text = "\n".join(all_issues[:30]) if all_issues else "Keine kritischen Issues gefunden."
    metrics_text = "\n".join(metrics)

    prompt = f"""Du bist ein freundlicher Web-Experte, der einem nicht-technischen Kunden erklärt, wie gut seine Website aufgestellt ist.

Schreibe eine kurze, verständliche Zusammenfassung (max. 300 Wörter, keine Fachbegriffe oder erkläre sie kurz in Klammern) der folgenden Audit-Ergebnisse für die Website: {url}

Beginne mit dem Gesamteindruck, nenne dann die 3 wichtigsten Probleme in einfacher Sprache und schließe mit einer positiven Ermutigung. Verwende keine Markdown-Tabellen, nur Fließtext mit gelegentlichen Aufzählungspunkten.

Kennzahlen:
{metrics_text}

Gefundene Probleme:
{issues_text}"""

    console.print("[dim]→ KI-Zusammenfassung wird generiert...[/dim]")

    with client.messages.stream(
        model="claude-sonnet-4-6",
        max_tokens=600,
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        text = stream.get_final_text()

    return text
