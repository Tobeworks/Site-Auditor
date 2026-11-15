import httpx
from bs4 import BeautifulSoup
from urllib.parse import urlparse

from auditor.findings import finding

# KI-Crawler, die eine robots.txt gezielt sperren kann. Anbieter ändern Namen, bei Bedarf ergänzen.
AI_CRAWLERS = [
    "GPTBot", "OAI-SearchBot", "ChatGPT-User", "ClaudeBot", "anthropic-ai",
    "PerplexityBot", "Google-Extended", "CCBot", "Applebot-Extended",
]
UA = {"User-Agent": "Mozilla/5.0 (compatible; site-auditor/1.0)"}


def _groups(text: str) -> list[tuple[list[str], list[tuple[str, str]]]]:
    """robots.txt in (Agenten, Regeln)-Gruppen zerlegen. Aufeinanderfolgende User-agent-Zeilen
    bilden eine Gruppe. ponytail: kein vollständiger RFC-9309-Parser, Pfadmuster werden nicht aufgelöst."""
    groups, agents, rules, in_rules = [], [], [], False
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key, value = key.strip().lower(), value.strip()
        if key == "user-agent":
            if in_rules:
                groups.append((agents, rules))
                agents, rules, in_rules = [], [], False
            agents.append(value.lower())
        elif key in ("allow", "disallow"):
            in_rules = True
            rules.append((key, value))
    if agents:
        groups.append((agents, rules))
    return groups


def _blocked(groups, bot: str) -> bool:
    """Gesperrt, wenn es eine Gruppe für genau diesen Crawler mit 'Disallow: /' gibt und kein 'Allow: /'.
    Bei Gleichstand gewinnt Allow (RFC 9309)."""
    for agents, rules in groups:
        if bot.lower() in agents:
            has = lambda kind: (kind, "/") in rules  # noqa: E731
            if has("disallow") and not has("allow"):
                return True
    return False


def _get(client, url: str) -> str | None:
    try:
        r = client.get(url)
    except httpx.HTTPError:
        return None
    return r.text if r.status_code == 200 else None


def run(url: str, html: str, soup: BeautifulSoup, headers: dict) -> dict:
    try:
        parsed = urlparse(url)
        base = f"{parsed.scheme}://{parsed.netloc}"
        findings = []
        with httpx.Client(timeout=8, follow_redirects=True, headers=UA) as client:
            robots = _get(client, f"{base}/robots.txt")
            llms = _get(client, f"{base}/llms.txt")

        blocked = [bot for bot in AI_CRAWLERS if robots and _blocked(_groups(robots), bot)]
        if blocked:
            findings.append(finding(
                "KIS-01", "MITTEL", f"robots.txt sperrt KI-Crawler: {', '.join(blocked)}",
                "ChatGPT, Claude & Co können deine Seite dann nicht lesen und nicht zitieren. Das kann eine bewusste Entscheidung sein.",
                solution="Wenn du in KI-Antworten vorkommen willst, nimm die Sperre dieser Crawler aus der robots.txt. Wenn nicht, ist alles in Ordnung.",
            ))

        # Ein HTML-Dokument unter /llms.txt ist meist eine Fehlerseite mit Status 200, keine llms.txt.
        has_llms = bool(llms and llms.strip() and not llms.lstrip().lower().startswith(("<!doctype", "<html")))
        if has_llms:
            findings.append(finding(
                "KIS-02", "POSITIV", "llms.txt vorhanden",
                "Eine kompakte Übersicht für KI-Dienste. Ein Nutzen ist bisher nicht belegt, schaden tut sie nicht.",
            ))

        return {"blocked_crawlers": blocked, "llms_txt": has_llms, "findings": findings}
    except Exception as e:
        return {"error": str(e)}
