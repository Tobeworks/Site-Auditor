import concurrent.futures
import json
import re
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
BLOCK_STATUS = (401, 403)  # 429 und 503 sind Drosselung und Ausfall, keine Aussage über Bot-Namen
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


def _probe(url: str, bot: str, baseline_ok: bool, budget: _Budget, baseline_head: str = "") -> tuple[str, int]:
    """Ruft die geprüfte Seite mit dem Namen eines Bots ab. Liefert (Ergebnis, Wörter im HTML dieser Antwort).
    'blocked' nur, wenn die normale Abfrage 200 lieferte, der Server den Bot abweist (401, 403 oder eine Prüfseite) und ein
    Kontrollabruf mit normaler Kennung unmittelbar danach noch 200 liefert. Sonst 'ok' bei Erfolg und 'unknown' bei allem anderen.
    Weiterleitungen nur innerhalb desselben Hosts. Wirft nie. Bekannte Grenzen: erkannt werden nur Sperren nach Bot-Namen, und
    Schutzsysteme, die den echten Bot an seiner IP-Adresse durchlassen, sperren unseren Abruf trotzdem."""
    if not baseline_ok:
        return "unknown", 0
    marked = lambda text: any(m in text[:2000].lower() and m not in baseline_head for m in CHALLENGE_MARKERS)  # noqa: E731
    try:
        current = url
        with httpx.Client(timeout=PROBE_TIMEOUT, follow_redirects=False, headers={"User-Agent": BOT_UA[bot]}, verify=False) as client:
            for _ in range(PROBE_MAX_REDIRECTS + 1):
                if not budget.take():
                    return "unknown", 0
                r = client.get(current)
                location = r.headers.get("location")
                if r.is_redirect and location:
                    current = str(r.url.join(location))
                    if not _same_host(url, current):
                        return "unknown", 0
                    continue
                rejected = r.status_code in BLOCK_STATUS or (200 <= r.status_code < 300 and marked(r.text))
                if rejected:
                    if not budget.take():
                        return "unknown", 0
                    control = client.get(current, headers=UA)   # läuft der Server mit normaler Kennung noch, ist es eine Sperre nach Bot-Namen
                    return ("blocked", 0) if control.status_code == 200 and not marked(control.text) else ("unknown", 0)
                if 200 <= r.status_code < 300:
                    return "ok", _word_count(BeautifulSoup(r.text, "lxml"))
                return "unknown", 0
    except Exception:
        pass
    return "unknown", 0


SKIP_TEXT_IN = {"script", "style", "noscript", "template"}
PAGE_FURNITURE = ("nav", "header", "footer")  # Listen dort sind Menüs, kein Inhalt
ORG_TYPES = {"Organization", "LocalBusiness", "Corporation", "ProfessionalService"}
ARTICLE_TYPES = {"Article", "BlogPosting", "NewsArticle"}
SNIPPET_TOKENS = {"nosnippet": "nosnippet", "noai": "noai", "noimageai": "noimageai"}
TEXT_RESTRICTIONS = {"nosnippet", "max-snippet:0", "noai"}  # noimageai betrifft nur Bilder und steht nur in der Liste
LONG_PAGE_WORDS = 300


def _word_count(soup) -> int:
    texts = (t for t in soup.find_all(string=True) if t.parent and t.parent.name not in SKIP_TEXT_IN)
    return sum(len(t.split()) for t in texts)


def _types(node) -> set:
    t = node.get("@type")
    return {x for x in (t if isinstance(t, list) else [t]) if isinstance(x, str)}


def _is_org(types: set) -> bool:
    return bool(types & ORG_TYPES) or any(t.endswith("Business") for t in types)


def _json_ld_nodes(soup) -> list[tuple[dict, bool]]:
    """Alle Schema-Knoten der Seite als (Knoten, oberste Ebene eines Blocks). @graph und Listen werden aufgelöst."""
    nodes = []

    def walk(data, top):
        if isinstance(data, list):
            for item in data:
                walk(item, False)
        elif isinstance(data, dict):
            nodes.append((data, top))
            if isinstance(data.get("@graph"), list):
                walk(data["@graph"], False)

    for script in soup.find_all("script", type="application/ld+json"):
        try:
            walk(json.loads(script.string or ""), True)
        except (json.JSONDecodeError, TypeError):
            continue
    return nodes


def _structure(soup, nodes) -> dict:
    headings = soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"])
    levels = [int(h.name[1]) for h in headings]
    questions = sum(1 for h in headings if h.get_text(" ", strip=True).endswith("?"))
    in_furniture = lambda el: any(p.name in PAGE_FURNITURE for p in el.parents)  # noqa: E731
    faq_questions = sum(1 for d in soup.find_all("summary") if d.get_text(" ", strip=True).endswith("?"))
    faq = (any("FAQPage" in _types(n) for n, _ in nodes) or faq_questions >= 2
           or bool(soup.find(attrs={"itemtype": re.compile(r"schema\.org/FAQPage", re.I)})))
    return {
        "heading_skips": sum(1 for a, b in zip(levels, levels[1:]) if b > a + 1),
        "h2_count": levels.count(2),
        "question_headings": questions,
        "lists": sum(1 for el in soup.find_all(["ul", "ol"]) if not in_furniture(el)),
        "tables": len(soup.find_all("table")),
        "faq": faq,
        "words": _word_count(soup),
    }


def _entity(nodes) -> dict:
    orgs = [n for n, _ in nodes if _is_org(_types(n))]
    persons = [n for n, _ in nodes if "Person" in _types(n)]  # Selbstständige beschreiben sich oft als Person
    articles = [n for n, _ in nodes if _types(n) & ARTICLE_TYPES]
    same_as = lambda n: len(n["sameAs"]) if isinstance(n.get("sameAs"), list) else 1 if n.get("sameAs") else 0  # noqa: E731
    return {
        "organization": bool(orgs or persons),
        "logo": any(n.get("logo") for n in orgs) or any(n.get("image") for n in persons),
        "same_as": max((same_as(n) for n in orgs + persons), default=0),
        "author": all(n.get("author") for n in articles) if articles else None,
        "date_modified": all(n.get("dateModified") for n in articles) if articles else None,
    }


def _entity_gaps(nodes) -> list[str]:
    """Was an der Firma und den Artikeln fehlt. Ausgenommen, was SDA-03 und SDA-04 schon melden: dort prüft structured_data
    nur Blöcke, deren oberste Ebene genau Organization oder Article ist."""
    gaps = []
    for node, top in nodes:
        types = _types(node)
        if _is_org(types) and not (top and types == {"Organization"}):
            gaps += [g for g, missing in (("logo", not node.get("logo")), ("sameAs", not node.get("sameAs"))) if missing]
        if types & ARTICLE_TYPES:
            gaps += [g for g, missing in (("dateModified", not node.get("dateModified")),
                                          ("author", not node.get("author") and not (top and types == {"Article"}))) if missing]
    return list(dict.fromkeys(gaps))


def _snippet_restrictions(soup, headers: dict) -> list[str]:
    values = []
    for meta in soup.find_all("meta", attrs={"name": re.compile(r"^(robots|googlebot|bingbot)$", re.I)}):
        values.append(meta.get("content") or "")
    values += [v for k, v in headers.items() if isinstance(k, str) and k.lower() == "x-robots-tag" and isinstance(v, str)]
    found = []
    for value in values:
        for token in (t.strip().lower().replace(" ", "") for t in value.split(",")):
            # "botname: nosnippet" gilt nur für einen bestimmten Bot und zählt hier nicht, im Zweifel kein Befund
            kind = "max-snippet:0" if token == "max-snippet:0" else SNIPPET_TOKENS.get(token)
            if kind and kind not in found:
                found.append(kind)
    return found


RENDER_MIN_WORDS = 40       # darunter ist die Seite zu kurz für ein belastbares Verhältnis
RENDER_HIGH_RATIO = 0.20    # weniger als ein Fünftel des sichtbaren Textes steht im HTML
RENDER_MEDIUM_RATIO = 0.34  # weniger als ein Drittel


def _checklist(result: dict) -> list[dict]:
    """Die fünf Gruppen als Checkliste für den Bericht, immer in dieser Reihenfolge."""
    ids = {f["id"] for f in result.get("findings", [])}
    crawlers = result.get("crawlers") or []
    structure, entity, render = result.get("structure") or {}, result.get("entity") or {}, result.get("render") or {}

    rejected = [c["name"] for c in crawlers if c.get("server") == "blocked"]
    robots_blocked = [c["name"] for c in crawlers if c.get("robots") == "blocked" and c.get("group") != "training"]
    if rejected or robots_blocked or "KIS-01" in ids or "KIS-03" in ids:
        access = ("issue", "Gesperrt: " + ", ".join(rejected + [b for b in robots_blocked if b not in rejected]))
    elif any(c.get("server") == "ok" for c in crawlers):
        access = ("ok", "Such- und Nutzer-Bots erreichen deine Seite.")
    else:
        access = ("unknown", "Der Abruf mit Bot-Namen war nicht möglich.")

    if "KIS-04" in ids:
        render_item = ("issue", f"Nur {render.get('html_words')} von {render.get('rendered_words')} Wörtern stehen im HTML.")
    elif render.get("status") == "ok":
        render_item = ("ok", "Der Text steht schon im HTML, ohne JavaScript.")
    else:
        render_item = ("unknown", "Nicht geprüft.")

    if not structure:
        structure_item = ("unknown", "Nicht geprüft.")
    else:
        detail = f"{structure.get('h2_count', 0)} Zwischenüberschriften, {structure.get('question_headings', 0)} Fragen, {structure.get('lists', 0)} Listen."
        structure_item = ("issue" if "KIS-05" in ids else "ok", detail)

    if not entity:
        entity_item = ("unknown", "Nicht geprüft.")
    else:
        missing = [name for name, ok in (("Firmen-Schema", entity.get("organization")), ("Logo", entity.get("logo")), ("sameAs-Profile", entity.get("same_as"))) if not ok]
        if "KIS-06" in ids:
            entity_item = ("issue", "Das Schema ist unvollständig" + (": " + ", ".join(missing) if missing else "") + ".")
        elif not missing:
            entity_item = ("ok", f"Firma, Logo und {entity['same_as']} Profile sind im Schema angegeben.")
        else:
            # kein eigener Befund (das meldet der Befund zu strukturierten Daten), die Liste behauptet deshalb keinen
            entity_item = ("unknown", "Es fehlt: " + ", ".join(missing) + ". Das steht im Befund zu strukturierten Daten.")

    restricted = (result.get("snippets") or {}).get("restricted") or []
    snippets = ("issue", "Gesperrt: " + ", ".join(restricted)) if "KIS-07" in ids else ("ok", "Keine Sperre für Textausschnitte.")

    items = (("access", "KI-Bots kommen auf deine Seite", access), ("render", "Dein Text ist ohne JavaScript lesbar", render_item),
             ("structure", "Deine Seite ist klar gegliedert", structure_item), ("entity", "Deine Firma ist eindeutig beschrieben", entity_item),
             ("snippets", "KI-Systeme dürfen Ausschnitte übernehmen", snippets))
    return [{"key": key, "label": label, "status": status, "detail": detail} for key, label, (status, detail) in items]


def apply_render_check(result: dict, html: str, first_view: dict | None) -> None:
    """Vergleicht den Text im HTML mit dem, was der Browser auf dem ersten Bildschirm zeigt, setzt `render`, hängt bei Bedarf
    KIS-04 an und baut die Checkliste neu. Tut nichts bei einem Fehler im Modul oder ohne brauchbares first_view. Im Zweifel
    kein Befund: html_words zählt die ganze Seite, rendered_words nur den ersten Bildschirm, ein Verhältnis unter 1 ist also streng."""
    if "error" in result or not isinstance(first_view, dict) or first_view.get("status") != "ok":
        return
    # Seiten, die Bots vorrendern, liefern ihnen mehr HTML als unserer normalen Abfrage: das Maximum zählt
    html_words = max(_word_count(BeautifulSoup(html or "", "lxml")), result.get("bot_html_words") or 0)
    rendered_words = len((first_view.get("text") or "").split())
    result["render"] = {"status": "ok", "html_words": html_words, "rendered_words": rendered_words}
    result["findings"] = [f for f in result["findings"] if f["id"] != "KIS-04"]
    if rendered_words >= RENDER_MIN_WORDS:
        ratio = html_words / rendered_words
        if ratio < RENDER_MEDIUM_RATIO:
            result["findings"].append(finding(
                "KIS-04", "HOCH" if ratio < RENDER_HIGH_RATIO else "MITTEL",
                f"Der Text deiner Seite steht nur mit JavaScript im Browser, im HTML sind es {html_words} von {rendered_words} Wörtern",
                "Viele KI-Crawler führen kein JavaScript aus. Sie sehen dann kaum Text von deiner Seite und können sie nicht verstehen oder zitieren.",
                solution="Liefere den Haupttext schon im HTML aus (Server-Rendering oder statische Seiten), statt ihn erst per JavaScript nachzuladen.",
            ))
    result["checklist"] = _checklist(result)


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
        servers, bot_words = {}, 0
        if targets:
            budget, baseline_head = _Budget(PROBE_BUDGET), (html or "")[:2000].lower()
            with concurrent.futures.ThreadPoolExecutor(max_workers=PROBE_WORKERS) as ex:
                probed = dict(zip(targets, ex.map(lambda bot: _probe(url, bot, baseline_ok, budget, baseline_head), targets)))
            servers = {bot: verdict for bot, (verdict, _) in probed.items()}
            bot_words = max((words for _, words in probed.values()), default=0)
        crawlers = [{"name": bot, "group": GROUP_OF[bot], "robots": robots_state(bot), "server": servers.get(bot, "unknown")} for bot in AI_CRAWLERS]

        rejected = [c["name"] for c in crawlers if c["server"] == "blocked"]
        if rejected:
            names = ", ".join(rejected)
            findings.append(finding(
                "KIS-03", "HOCH" if len(rejected) >= 2 else "MITTEL",
                f"Dein Server weist Abrufe ab, die sich als diese KI-Bots ausgeben, obwohl die robots.txt sie erlaubt: {names}",
                "Diese KI-Systeme bekommen deine Seite womöglich nicht zu sehen und können sie dann nicht lesen und nicht zitieren. "
                "Manche Schutzsysteme lassen die echten Bots von ihren festen Adressen trotzdem durch, dann ist alles in Ordnung.",
                solution=f"Prüfe Firewall, Bot-Schutz (zum Beispiel bei Cloudflare) und Sicherheits-Plugins und erlaube die Bots {names}, wenn du in KI-Antworten vorkommen willst.",
            ))

        # Struktur, eindeutige Firma, Übernahme erlaubt
        nodes = _json_ld_nodes(soup)
        structure, entity = _structure(soup, nodes), _entity(nodes)
        restricted = _snippet_restrictions(soup, headers)
        if structure["words"] >= LONG_PAGE_WORDS and structure["h2_count"] == 0:
            findings.append(finding(
                "KIS-05", "MITTEL", "Deine Seite hat viel Text, aber keine Zwischenüberschriften (H2)",
                "KI-Systeme zerlegen Seiten anhand der Überschriften in Abschnitte. Ohne sie lassen sich einzelne Antworten schlecht herausziehen.",
                solution="Gliedere den Text mit Zwischenüberschriften (H2), am besten als Fragen, die deine Kunden stellen.",
            ))
        gaps = _entity_gaps(nodes)
        if gaps:
            findings.append(finding(
                "KIS-06", "MITTEL", f"Deine Firma ist im Schema nicht vollständig beschrieben, es fehlt: {', '.join(gaps)}",
                "KI-Systeme ordnen Aussagen nur dann sicher dir zu, wenn Firma, Logo und Profile (sameAs) eindeutig angegeben sind.",
                solution=f"Ergänze im Schema-Block deiner Firma beziehungsweise des Artikels: {', '.join(gaps)}.",
            ))
        text_restricted = [r for r in restricted if r in TEXT_RESTRICTIONS]
        if text_restricted:
            findings.append(finding(
                "KIS-07", "MITTEL", f"Deine Seite verbietet das Übernehmen von Textausschnitten ({', '.join(text_restricted)})",
                "Suchmaschinen und KI-Systeme dürfen dann keine Ausschnitte deiner Seite anzeigen oder in Antworten übernehmen.",
                solution="Entferne die Sperre aus dem Robots-Meta-Tag oder dem X-Robots-Tag-Header, wenn Ausschnitte erwünscht sind. Wenn die Sperre Absicht ist, ist alles in Ordnung.",
            ))
        if structure["question_headings"] or structure["faq"]:
            findings.append(finding(
                "KIS-08", "POSITIV", "Deine Seite enthält Fragen und Antworten",
                "Fragen als Überschriften und FAQ-Abschnitte lassen sich von KI-Systemen leicht als Antwort übernehmen.",
            ))

        result = {"blocked_crawlers": blocked, "llms_txt": has_llms, "crawlers": crawlers, "structure": structure,
                  "entity": entity, "snippets": {"restricted": restricted},
                  "render": {"status": "unknown", "html_words": None, "rendered_words": None},
                  "bot_html_words": bot_words or None, "findings": findings}
        result["checklist"] = _checklist(result)
        return result
    except Exception as e:
        return {"error": str(e)}
