import httpx
from bs4 import BeautifulSoup

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

        issues = []
        for m in errors[:10]:
            line = m.get("lastLine")
            issues.append(f"Zeile {line}: {m.get('message', '')}" if line else m.get("message", ""))
        if len(errors) > 10:
            issues.append(f"... und {len(errors) - 10} weitere Markup-Fehler")

        return {
            "errors": errors,
            "warnings": warnings,
            "error_count": len(errors),
            "warning_count": len(warnings),
            "issues": issues,
        }
    except Exception as e:
        return {"error": str(e)}
