import concurrent.futures
import threading

import httpx
from bs4 import BeautifulSoup
from urllib.parse import urlparse

from auditor.findings import finding

# KI-Crawler, die eine robots.txt gezielt sperren kann. Anbieter ändern Namen und Zwecke, bei Bedarf prüfen und ergänzen.
# Zweck laut Anbieterangaben und Fachquellen (Stand 16.11.2026, die Quellen sind sich bei ClaudeBot und PerplexityBot nicht
# ganz einig): nur das Sperren von Such- und Nutzer-Crawlern verhindert, dass die Seite in KI-Suchen und Antworten auftaucht.
# Das Sperren des Trainings ist eine verbreitete, bewusste Entscheidung.
SEARCH_BOTS = ["OAI-SearchBot", "Claude-SearchBot", "PerplexityBot"]
USER_BOTS = ["ChatGPT-User", "Claude-User", "Perplexity-User"]
SEARCH_CRAWLERS = SEARCH_BOTS + USER_BOTS  # Grundlage von KIS-01
TRAINING_CRAWLERS = ["GPTBot", "ClaudeBot", "anthropic-ai", "Google-Extended", "CCBot", "Applebot-Extended"]
AI_CRAWLERS = SEARCH_CRAWLERS + TRAINING_CRAWLERS
GROUP_OF = {**{b: "search" for b in SEARCH_BOTS}, **{b: "user" for b in USER_BOTS}, **{b: "training" for b in TRAINING_CRAWLERS}}

# Browser-Kennungen im Format der Anbieter, Stand 16.11.2026 aus der Erinnerung an deren Dokumentation, vor einem Einsatz
# gegen eine bestimmte Bot-Abwehr gegen die Anbieter-Seiten prüfen. Entscheidend ist der Bot-Name im User-Agent.
BOT_UA = {
    bot: f"Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; {bot}/{version}; +{info})"
    for bot, version, info in (
        ("OAI-SearchBot", "1.3", "https://openai.com/searchbot"),
        ("ChatGPT-User", "1.0", "https://openai.com/bot"),
        ("PerplexityBot", "1.0", "https://perplexity.ai/perplexitybot"),
        ("Perplexity-User", "1.0", "https://perplexity.ai/perplexity-user"),
        ("Claude-SearchBot", "1.0", "Claudebot@anthropic.com"),
        ("Claude-User", "1.0", "Claude-User@anthropic.com"),
    )
}

# Abruf mit Bot-Namen: nur Such- und Nutzer-Bots, nur die geprüfte Seite, kurz, ohne Wiederholung.
PROBE_TIMEOUT = 8
PROBE_BUDGET = 10  # Höchstzahl der Abrufe mit Bot-Namen je Lauf, Weiterleitungen eingerechnet
PROBE_MAX_REDIRECTS = 2
PROBE_WORKERS = 3
BLOCK_STATUS = (401, 403, 429, 503)
CHALLENGE_MARKERS = ("just a moment", "cf-chl", "attention required", "access denied")
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


def _same_host(a: str, b: str) -> bool:
    """Gleicher Host und Port, ein führendes www. gilt als gleich."""
    host = lambda u: urlparse(u).netloc.lower().removeprefix("www.")  # noqa: E731
    return bool(host(a)) and host(a) == host(b)


class _Budget:
    def __init__(self, total: int):
        self._left, self._lock = total, threading.Lock()

    def take(self) -> bool:
        with self._lock:
            if self._left <= 0:
                return False
            self._left -= 1
            return True


def _probe(url: str, bot: str, baseline_ok: bool, budget: _Budget, baseline_head: str = "") -> str:
    """Ruft die geprüfte Seite mit dem Namen eines Bots ab. 'blocked' nur, wenn die normale Abfrage 200 lieferte und der Server
    den Bot abweist (401, 403, 429, 503 oder eine Prüfseite), sonst 'ok' bei Erfolg und 'unknown' bei allem anderen.
    Weiterleitungen nur innerhalb desselben Hosts. Wirft nie. Bekannte Grenze: erkannt werden nur Sperren nach Bot-Namen."""
    if not baseline_ok:
        return "unknown"
    try:
        current = url
        with httpx.Client(timeout=PROBE_TIMEOUT, follow_redirects=False, headers={"User-Agent": BOT_UA[bot]}, verify=False) as client:
            for _ in range(PROBE_MAX_REDIRECTS + 1):
                if not budget.take():
                    return "unknown"
                r = client.get(current)
                location = r.headers.get("location")
                if r.is_redirect and location:
                    current = str(r.url.join(location))
                    if not _same_host(url, current):
                        return "unknown"
                    continue
                if r.status_code in BLOCK_STATUS:
                    return "blocked"
                if 200 <= r.status_code < 300:
                    head = r.text[:2000].lower()
                    # eine Marke, die schon die normale Seite trägt, ist keine Prüfseite
                    return "blocked" if any(m in head and m not in baseline_head for m in CHALLENGE_MARKERS) else "ok"
                return "unknown"
    except Exception:
        pass
    return "unknown"


def run(url: str, html: str, soup: BeautifulSoup, headers: dict) -> dict:
    try:
        parsed = urlparse(url)
        base = f"{parsed.scheme}://{parsed.netloc}"
        findings = []
        with httpx.Client(timeout=8, follow_redirects=True, headers=UA) as client:
            robots = _get(client, f"{base}/robots.txt")
            llms = _get(client, f"{base}/llms.txt")

        blocked = [bot for bot in AI_CRAWLERS if robots and _blocked(_groups(robots), bot)]
        blocked_search = [bot for bot in blocked if bot in SEARCH_CRAWLERS]
        if blocked_search:
            findings.append(finding(
                "KIS-01", "MITTEL", f"robots.txt sperrt KI-Such-Crawler: {', '.join(blocked_search)}",
                "Deine Seite kann in der KI-Suche dieser Anbieter nicht gelesen und nicht zitiert werden. Das kann eine bewusste Entscheidung sein.",
                solution="Wenn du in KI-Antworten vorkommen willst, nimm die Sperre dieser Crawler aus der robots.txt. Wenn nicht, ist alles in Ordnung.",
            ))

        # Ein HTML-Dokument unter /llms.txt ist meist eine Fehlerseite mit Status 200, keine llms.txt.
        has_llms = bool(llms and llms.strip() and not llms.lstrip().lower().startswith(("<!doctype", "<html")))
        if has_llms:
            findings.append(finding(
                "KIS-02", "POSITIV", "llms.txt vorhanden",
                "Eine kompakte Übersicht für KI-Dienste. Ein Nutzen ist bisher nicht belegt, schaden tut sie nicht.",
            ))

        # Zugang: robots.txt je Bot und ein echter Abruf mit dem Bot-Namen (nur Such- und Nutzer-Bots, nur bei bekanntem Status 200)
        parsed_robots = _groups(robots) if robots else []
        robots_state = lambda bot: "unknown" if robots is None else ("blocked" if _blocked(parsed_robots, bot) else "allowed")  # noqa: E731
        baseline_ok = headers.get("_status_code") == 200
        targets = [bot for bot in SEARCH_CRAWLERS if baseline_ok and robots_state(bot) != "blocked"]
        servers = {}
        if targets:
            budget, baseline_head = _Budget(PROBE_BUDGET), (html or "")[:2000].lower()
            with concurrent.futures.ThreadPoolExecutor(max_workers=PROBE_WORKERS) as ex:
                servers = dict(zip(targets, ex.map(lambda bot: _probe(url, bot, baseline_ok, budget, baseline_head), targets)))
        crawlers = [{"name": bot, "group": GROUP_OF[bot], "robots": robots_state(bot), "server": servers.get(bot, "unknown")} for bot in AI_CRAWLERS]

        rejected = [c["name"] for c in crawlers if c["server"] == "blocked"]
        if rejected:
            names = ", ".join(rejected)
            findings.append(finding(
                "KIS-03", "HOCH", f"Dein Server weist diese KI-Bots ab, obwohl die robots.txt sie erlaubt: {names}",
                "Diese KI-Systeme bekommen deine Seite nicht zu sehen. Sie können sie nicht lesen und nicht zitieren, auch wenn du es willst.",
                solution=f"Prüfe Firewall, Bot-Schutz (zum Beispiel bei Cloudflare) und Sicherheits-Plugins und erlaube die Bots {names}, wenn du in KI-Antworten vorkommen willst.",
            ))

        return {"blocked_crawlers": blocked, "llms_txt": has_llms, "crawlers": crawlers, "findings": findings}
    except Exception as e:
        return {"error": str(e)}
