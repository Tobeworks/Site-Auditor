import httpx
from bs4 import BeautifulSoup

from auditor.findings import finding

VALIDATOR_URL = "https://validator.w3.org/nu/?out=json"


def run(url: str, html: str, soup: BeautifulSoup, headers: dict) -> dict:
    try:
        r = httpx.post(
            VALIDATOR_URL,
            content=html.encode("utf-8"),
            headers={
                "Content-Type": "text/html; charset=utf-8",
                "User-Agent": "Mozilla/5.0 (compatible; site-auditor/1.0)",
            },
            timeout=15,
        )
        r.raise_for_status()
        messages = r.json().get("messages", [])

        errors = [m for m in messages if m.get("type") == "error"]
        warnings = [m for m in messages if m.get("type") in ("info", "warning")]

        findings = []
        for m in errors[:10]:
            line = m.get("lastLine")
            text = f"Zeile {line}: {m.get('message', '')}" if line else m.get("message", "")
            findings.append(finding("MKP-01", "MITTEL", text,
                "Ungültiges HTML kann von Browsern und Screenreadern inkonsistent interpretiert werden.",
                solution="Markup-Fehler beheben (siehe Zeilenangabe), Struktur gegen die HTML-Spezifikation prüfen."))
        if len(errors) > 10:
            findings.append(finding("MKP-01", "MITTEL", f"... und {len(errors) - 10} weitere Markup-Fehler (insgesamt {len(errors)})",
                "Ungültiges HTML kann von Browsern und Screenreadern inkonsistent interpretiert werden.",
                solution="Vollständigen W3C-Validator-Report prüfen und alle Fehler beheben."))
        if not errors:
            findings.append(finding("MKP-01", "POSITIV", f"Keine W3C-Markup-Fehler gefunden ({len(warnings)} Warnung(en))",
                "HTML ist spezifikationskonform."))

        return {
            "errors": errors,
            "warnings": warnings,
            "error_count": len(errors),
            "warning_count": len(warnings),
            "findings": findings,
        }
    except Exception as e:
        return {"error": str(e)}
