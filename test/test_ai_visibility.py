"""Assert-based smoke test for auditor.checks.ai_visibility. Run: uv run python test/test_ai_visibility.py"""
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch, MagicMock
from bs4 import BeautifulSoup
from auditor.checks import ai_visibility


def _client_mock(robots_txt=None, llms_txt=None):
    client = MagicMock()
    client.__enter__.return_value = client

    def get(url, **kw):
        if url.endswith("/robots.txt") and robots_txt is not None:
            return MagicMock(status_code=200, text=robots_txt)
        if url.endswith("/llms.txt") and llms_txt is not None:
            return MagicMock(status_code=200, text=llms_txt)
        return MagicMock(status_code=404, text="")

    client.get.side_effect = get
    return client


def _run(robots_txt=None, llms_txt=None):
    with patch("httpx.Client", return_value=_client_mock(robots_txt, llms_txt)):
        return ai_visibility.run("https://x.de/", "<html></html>", BeautifulSoup("", "lxml"), {})


def test_blocked_search_crawler_is_reported():
    result = _run("User-agent: OAI-SearchBot\nDisallow: /\n")
    assert result["blocked_crawlers"] == ["OAI-SearchBot"]
    f = next(f for f in result["findings"] if f["id"] == "KIS-01")
    assert f["severity"] == "MITTEL"
    assert "OAI-SearchBot" in f["finding"] and "KI-Suche" in f["impact"]


def test_training_only_block_is_listed_but_gives_no_finding():
    # Das Training zu sperren ist eine verbreitete, bewusste Entscheidung und sagt nichts über Antworten in KI-Suchen.
    result = _run("User-agent: GPTBot\nUser-agent: CCBot\nUser-agent: Google-Extended\nDisallow: /\n\nUser-agent: OAI-SearchBot\nAllow: /\n")
    assert result["blocked_crawlers"] == ["GPTBot", "Google-Extended", "CCBot"] or set(result["blocked_crawlers"]) == {"GPTBot", "CCBot", "Google-Extended"}
    assert not any(f["id"] == "KIS-01" for f in result["findings"])


def test_wildcard_disallow_alone_is_not_an_ai_finding():
    # Die Gesamtsperre meldet SOC-01, hier wird nur gezielt gegen KI-Crawler gemeldet.
    result = _run("User-agent: *\nDisallow: /\n")
    assert result["blocked_crawlers"] == []
    assert not any(f["id"] == "KIS-01" for f in result["findings"])


def test_allow_after_disallow_is_not_blocked():
    result = _run("User-agent: ClaudeBot\nDisallow: /\nAllow: /\n")
    assert result["blocked_crawlers"] == []


def test_partial_disallow_is_not_blocked():
    result = _run("User-agent: GPTBot\nDisallow: /intern/\n")
    assert result["blocked_crawlers"] == []


def test_several_agents_in_one_group_are_all_blocked():
    result = _run("User-agent: GPTBot\nUser-agent: PerplexityBot\nDisallow: /\n")
    assert set(result["blocked_crawlers"]) == {"GPTBot", "PerplexityBot"}
    assert "PerplexityBot" in next(f for f in result["findings"] if f["id"] == "KIS-01")["finding"]


def test_no_robots_txt_no_finding():
    result = _run(None)
    assert result["blocked_crawlers"] == []
    assert result["findings"] == []


def test_llms_txt_present_is_positive_only():
    result = _run(None, "# Seite\n> Kurzbeschreibung\n")
    assert result["llms_txt"] is True
    f = next(f for f in result["findings"] if f["id"] == "KIS-02")
    assert f["severity"] == "POSITIV"


def test_missing_llms_txt_gives_no_finding():
    result = _run(None, None)
    assert result["llms_txt"] is False
    assert not any(f["id"] == "KIS-02" for f in result["findings"])


def test_html_soft_404_is_not_an_llms_txt():
    result = _run(None, "<!DOCTYPE html><html><body>Seite nicht gefunden</body></html>")
    assert result["llms_txt"] is False


def test_error_path_returns_error_key():
    with patch("httpx.Client", side_effect=RuntimeError("boom")):
        result = ai_visibility.run("https://x.de/", "<html></html>", BeautifulSoup("", "lxml"), {})
    assert "error" in result



# ---- Zugang: echte Bot-Abrufe gegen einen lokalen Server (kein Internet) ----

PROBED = ["OAI-SearchBot", "Claude-SearchBot", "PerplexityBot", "ChatGPT-User", "Claude-User", "Perplexity-User"]
TRAINING = ["GPTBot", "ClaudeBot", "anthropic-ai", "Google-Extended", "CCBot", "Applebot-Extended"]
OK_HTML = "<html><body><h1>Willkommen</h1></body></html>"


def _serve(rule=None, robots=None, delay=None):
    """rule(user_agent, path) -> (status, body, headers) oder None für die normale Seite. Liefert (server, basis_url, zugriffe)."""
    hits = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            ua = self.headers.get("User-Agent", "")
            hits.append((self.path, ua))
            if self.path == "/robots.txt":
                status, body, headers = (200, robots, {}) if robots is not None else (404, "", {})
            else:
                if delay and delay(ua):
                    time.sleep(delay(ua))
                status, body, headers = (rule(ua, self.path) if rule else None) or (200, OK_HTML, {})
            data = body.encode()
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            for key, value in headers.items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}", hits


def _bot_hits(hits, bots=PROBED + TRAINING):
    return [(path, ua) for path, ua in hits if any(bot in ua for bot in bots)]


def _run_live(base, headers=None, html=OK_HTML):
    headers = {"_status_code": 200} if headers is None else headers
    return ai_visibility.run(base + "/", html, BeautifulSoup(html, "lxml"), headers)


def _entry(result, name):
    return next(c for c in result["crawlers"] if c["name"] == name)


def test_crawlers_list_has_group_robots_and_server_status():
    server, base, hits = _serve()
    try:
        result = _run_live(base)
    finally:
        server.shutdown()
    assert "error" not in result
    assert {c["name"] for c in result["crawlers"]} == set(PROBED + TRAINING)
    for bot, group in (("OAI-SearchBot", "search"), ("Claude-SearchBot", "search"), ("PerplexityBot", "search"),
                       ("ChatGPT-User", "user"), ("Claude-User", "user"), ("Perplexity-User", "user"), ("GPTBot", "training")):
        assert _entry(result, bot)["group"] == group, bot
    for bot in PROBED:
        assert _entry(result, bot)["server"] == "ok" and _entry(result, bot)["robots"] in ("allowed", "unknown"), bot
    for bot in TRAINING:
        assert _entry(result, bot)["server"] == "unknown", bot
    assert _bot_hits(hits, TRAINING) == []   # Training wird nie abgerufen
    assert not any(f["id"] == "KIS-03" for f in result["findings"])


def test_server_rejecting_a_search_bot_is_a_finding():
    server, base, _ = _serve(lambda ua, path: (403, "Verboten", {}) if "OAI-SearchBot" in ua else None)
    try:
        result = _run_live(base)
    finally:
        server.shutdown()
    assert _entry(result, "OAI-SearchBot")["server"] == "blocked"
    assert all(_entry(result, bot)["server"] == "ok" for bot in PROBED if bot != "OAI-SearchBot")
    f = next(f for f in result["findings"] if f["id"] == "KIS-03")
    assert f["severity"] == "MITTEL" and f["solution"] and "OAI-SearchBot" in f["finding"] + f["solution"]   # ein einzelner Bot kann ein Zufall der Abwehr sein


def test_challenge_page_counts_as_blocked():
    server, base, _ = _serve(lambda ua, path: (200, "<html><title>Just a moment...</title></html>", {}) if "PerplexityBot" in ua else None)
    try:
        result = _run_live(base)
    finally:
        server.shutdown()
    assert _entry(result, "PerplexityBot")["server"] == "blocked"


def test_unknown_baseline_gives_no_finding():
    for headers in ({}, {"_status_code": 403}):
        server, base, hits = _serve(lambda ua, path: (403, "Verboten", {}))
        try:
            result = _run_live(base, headers)
        finally:
            server.shutdown()
        assert all(c["server"] == "unknown" for c in result["crawlers"]), headers
        assert not any(f["id"] == "KIS-03" for f in result["findings"])
        assert _bot_hits(hits) == []


def test_robots_blocked_bot_is_not_probed_and_not_double_reported():
    server, base, hits = _serve(lambda ua, path: (403, "Verboten", {}) if "OAI-SearchBot" in ua else None,
                                robots="User-agent: OAI-SearchBot\nDisallow: /\n")
    try:
        result = _run_live(base)
    finally:
        server.shutdown()
    entry = _entry(result, "OAI-SearchBot")
    assert entry["robots"] == "blocked" and entry["server"] == "unknown"
    assert _bot_hits(hits, ["OAI-SearchBot"]) == []
    assert not any(f["id"] == "KIS-03" for f in result["findings"]) and any(f["id"] == "KIS-01" for f in result["findings"])


def test_redirect_to_other_host_is_not_followed_and_same_host_is():
    server_b, base_b, hits_b = _serve()

    def rule(ua, path):
        if "Claude-User" in ua and path == "/":
            return 302, "", {"Location": base_b + "/"}
        if "ChatGPT-User" in ua and path == "/":
            return 302, "", {"Location": "/landing"}
        return None
    server_a, base_a, hits_a = _serve(rule)
    try:
        result = _run_live(base_a)
    finally:
        server_a.shutdown()
        server_b.shutdown()
    assert _entry(result, "Claude-User")["server"] == "unknown" and hits_b == []
    assert _entry(result, "ChatGPT-User")["server"] == "ok" and any(path == "/landing" for path, _ in hits_a)


def test_same_host_ignores_www_and_nothing_else():
    same = ai_visibility._same_host
    assert same("https://beispiel.de/", "https://www.beispiel.de/x") and same("https://www.beispiel.de/", "http://beispiel.de/")
    assert not same("https://beispiel.de/", "https://andere.de/") and not same("https://beispiel.de/", "https://beispiel.de.evil.de/")
    assert not same("http://127.0.0.1:8000/", "http://127.0.0.1:9000/")


def test_probe_failures_do_not_raise():
    # geschlossener Port
    import socket
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    result = ai_visibility.run(f"http://127.0.0.1:{port}/", OK_HTML, BeautifulSoup(OK_HTML, "lxml"), {"_status_code": 200})
    assert "error" not in result and all(c["server"] == "unknown" for c in result["crawlers"])
    # Zeitüberschreitung
    server, base, _ = _serve(delay=lambda ua: 1.5 if "Claude-User" in ua else 0)
    try:
        with patch.object(ai_visibility, "PROBE_TIMEOUT", 0.3):
            result = _run_live(base)
    finally:
        server.shutdown()
    assert "error" not in result and _entry(result, "Claude-User")["server"] == "unknown"
    assert _entry(result, "OAI-SearchBot")["server"] == "ok"


def test_probe_request_count_is_limited():
    server, base, hits = _serve()
    try:
        _run_live(base)
    finally:
        server.shutdown()
    assert len(_bot_hits(hits)) == 6
    # auch mit Weiterleitungsschleife höchstens zehn Abrufe mit Bot-Namen
    server, base, hits = _serve(lambda ua, path: (302, "", {"Location": "/loop"}) if _bot_hits([("", ua)]) else None)
    try:
        _run_live(base)
    finally:
        server.shutdown()
    assert len(_bot_hits(hits)) <= 10, len(_bot_hits(hits))


def test_fetch_reports_the_status_code():
    from auditor import runner
    server, base, _ = _serve()
    try:
        html, headers, _ms = runner._fetch(base + "/")
    finally:
        server.shutdown()
    assert html and headers["_status_code"] == 200



# ---- Struktur, Firma, Snippet-Sperren (reine Auswertung von soup und headers, kein Netz) ----
import json as _json


def _analyze(html, headers=None):
    soup = BeautifulSoup(html, "lxml")
    with patch("httpx.Client", return_value=_client_mock()):
        return ai_visibility.run("https://x.de/", html, soup, headers or {})


def _ld(data):
    return f'<script type="application/ld+json">{_json.dumps(data)}</script>'


def _ids(result):
    return [f["id"] for f in result["findings"]]


def _page(body, head="", words=0):
    return f"<html><head>{head}</head><body>{body}<p>{'wort ' * words}</p></body></html>"


def test_structure_counts_headings_lists_tables_questions_and_faq():
    html = _page(
        "<h1>Titel</h1><h2>Was kostet das?</h2><h4>Wie lange dauert es?</h4><ul><li>a</li></ul><table><tr><td>x</td></tr></table>",
        head=_ld({"@type": "FAQPage", "mainEntity": []}),
    )
    s = _analyze(html)["structure"]
    assert (s["heading_skips"], s["h2_count"], s["question_headings"], s["lists"], s["tables"], s["faq"]) == (1, 1, 2, 1, 1, True)
    assert s["words"] > 0


def test_lists_in_navigation_are_not_counted():
    html = _page("<nav><ul><li>Menü</li></ul></nav><footer><ul><li>Fuß</li></ul></footer><h1>T</h1><h2>U</h2><ol><li>1</li></ol>")
    assert _analyze(html)["structure"]["lists"] == 1


def test_long_page_without_any_h2_gets_kis_05():
    result = _analyze(_page("<h1>Titel</h1>", words=350))
    f = next(f for f in result["findings"] if f["id"] == "KIS-05")
    assert f["severity"] == "MITTEL" and f["solution"]


def test_short_page_never_gets_a_structure_finding():
    assert "KIS-05" not in _ids(_analyze(_page("<h1>Titel</h1>", words=60)))
    assert "KIS-05" not in _ids(_analyze(_page("<h1>Titel</h1><h2>Teil</h2>", words=400)))


def test_organization_incomplete_in_graph_gets_kis_06_but_top_level_is_left_to_sda():
    graph = {"@context": "https://schema.org", "@graph": [{"@type": "Organization", "name": "Muster", "url": "https://x.de/"}]}
    result = _analyze(_page("<h1>T</h1>", head=_ld(graph)))
    assert "KIS-06" in _ids(result) and result["entity"]["organization"] is True
    assert result["entity"]["logo"] is False and result["entity"]["same_as"] == 0
    top = _analyze(_page("<h1>T</h1>", head=_ld({"@type": "Organization", "name": "Muster", "url": "https://x.de/"})))
    assert "KIS-06" not in _ids(top)   # SDA-04 meldet fehlendes Logo und sameAs dort schon
    assert top["entity"]["logo"] is False


def test_complete_or_missing_organization_gets_no_kis_06():
    complete = {"@context": "https://schema.org", "@graph": [
        {"@type": "Organization", "name": "Muster", "url": "https://x.de/", "logo": "https://x.de/l.png", "sameAs": ["https://www.linkedin.com/company/x"]}]}
    result = _analyze(_page("<h1>T</h1>", head=_ld(complete)))
    assert "KIS-06" not in _ids(result) and result["entity"]["logo"] is True and result["entity"]["same_as"] == 1
    none = _analyze(_page("<h1>T</h1>"))
    assert "KIS-06" not in _ids(none) and none["entity"]["organization"] is False   # das meldet SDA-02


def test_article_without_author_or_date_is_reported_only_for_articles():
    article = {"@type": "Article", "headline": "H", "datePublished": "2026-01-01"}
    result = _analyze(_page("<h1>T</h1>", head=_ld(article)))
    assert result["entity"]["author"] is False and result["entity"]["date_modified"] is False
    f = next(f for f in result["findings"] if f["id"] == "KIS-06")
    assert "dateModified" in f["finding"] + f["solution"]
    page = _analyze(_page("<h1>T</h1>"))
    assert page["entity"]["author"] is None and page["entity"]["date_modified"] is None


def test_snippet_restrictions_are_found_in_meta_and_header():
    html = _page("<h1>T</h1>", head='<meta name="robots" content="index, nosnippet"><meta name="googlebot" content="max-snippet: 0">')
    result = _analyze(html, {"X-Robots-Tag": "noai, noimageai"})
    assert set(result["snippets"]["restricted"]) == {"nosnippet", "max-snippet:0", "noai", "noimageai"}
    f = next(f for f in result["findings"] if f["id"] == "KIS-07")
    assert f["severity"] == "MITTEL" and "nosnippet" in f["finding"] and "noimageai" not in f["finding"]


def test_page_without_restrictions_has_no_kis_07():
    for html, headers in ((_page("<h1>T</h1>"), {}),
                          (_page('<h1>T</h1><p data-nosnippet>intern</p>', head='<meta name="robots" content="index, follow, max-snippet:-1">'), {}),
                          (_page("<h1>T</h1>"), {"x-robots-tag": "otherbot: nosnippet"})):
        result = _analyze(html, headers)
        assert result["snippets"]["restricted"] == [] and "KIS-07" not in _ids(result)


def test_question_headings_or_faq_give_positive_kis_08():
    for html in (_page("<h1>T</h1><h2>Was kostet das?</h2>"), _page("<h1>T</h1>", head=_ld({"@type": "FAQPage", "mainEntity": []}))):
        f = next(f for f in _analyze(html)["findings"] if f["id"] == "KIS-08")
        assert f["severity"] == "POSITIV"
    assert "KIS-08" not in _ids(_analyze(_page("<h1>T</h1><h2>Leistungen</h2>")))


def test_findings_and_result_stay_valid_without_html():
    result = ai_visibility.run("https://x.de/", "", BeautifulSoup("", "lxml"), {})
    assert "error" not in result and result["findings"] == []
    assert result["structure"]["words"] == 0 and result["structure"]["lists"] == 0
    assert result["entity"] == {"organization": False, "logo": False, "same_as": 0, "author": None, "date_modified": None}
    assert result["snippets"] == {"restricted": []}



# ---- Lesbarkeit ohne JavaScript, Checkliste ----

def _fv(words, status="ok"):
    return {"status": status, "title": "", "description": "", "h1": "", "text": " ".join(["wort"] * words)}


def _base_result():
    return _analyze(_page("<h1>T</h1><h2>Teil</h2>"))


def _html_with(words):
    return f"<html><body><p>{'wort ' * words}</p><script>var viel = 'a b c d e f g h i j k l m n o p';</script></body></html>"


def test_render_check_flags_js_only_pages():
    for html_words, rendered, severity in ((30, 300, "HOCH"), (90, 300, "MITTEL"), (240, 300, None)):
        result = _base_result()
        ai_visibility.apply_render_check(result, _html_with(html_words), _fv(rendered))
        assert result["render"]["status"] == "ok" and result["render"]["rendered_words"] == rendered
        assert result["render"]["html_words"] == html_words   # Skripte zählen nicht mit
        found = [f for f in result["findings"] if f["id"] == "KIS-04"]
        assert (found[0]["severity"] if found else None) == severity, (html_words, rendered)
        if found:
            assert found[0]["solution"] and "JavaScript" in found[0]["finding"]


def test_render_check_ignores_short_pages():
    result = _base_result()
    ai_visibility.apply_render_check(result, _html_with(2), _fv(25))
    assert not any(f["id"] == "KIS-04" for f in result["findings"]) and result["render"]["status"] == "ok"


def test_render_check_without_usable_first_view_changes_nothing():
    for fv in (_fv(300, "blocked"), _fv(0, "empty"), _fv(0, "error"), None):
        result = _base_result()
        before = list(result["findings"])
        ai_visibility.apply_render_check(result, _html_with(5), fv)
        assert result["render"]["status"] == "unknown" and result["findings"] == before, fv
    failed = {"error": "boom"}
    ai_visibility.apply_render_check(failed, _html_with(5), _fv(300))
    assert failed == {"error": "boom"}


def _checklist_status(result):
    assert [c["key"] for c in result["checklist"]] == ["access", "render", "structure", "entity", "snippets"]
    assert all(c["label"] and c["detail"] and c["status"] in ("ok", "issue", "unknown") for c in result["checklist"])
    return {c["key"]: c["status"] for c in result["checklist"]}


def test_checklist_has_five_entries_in_fixed_order_with_status():
    complete = {"@context": "https://schema.org", "@graph": [{"@type": "Organization", "name": "M", "url": "https://x.de/", "logo": "l", "sameAs": ["https://a.de"]}]}
    good = _analyze(_page("<h1>T</h1><h2>Teil</h2>", head=_ld(complete)))
    status = _checklist_status(good)
    assert status == {"access": "unknown", "render": "unknown", "structure": "ok", "entity": "ok", "snippets": "ok"}
    ai_visibility.apply_render_check(good, _html_with(280), _fv(300))
    assert _checklist_status(good)["render"] == "ok"
    ai_visibility.apply_render_check(good, _html_with(20), _fv(300))   # baut die Liste neu
    assert _checklist_status(good)["render"] == "issue"
    bad = _analyze(_page("<h1>T</h1>", head='<meta name="robots" content="nosnippet">', words=350))
    assert _checklist_status(bad) == {"access": "unknown", "render": "unknown", "structure": "issue", "entity": "unknown", "snippets": "issue"}


def test_checklist_access_follows_crawlers_and_robots():
    server, base, _ = _serve(lambda ua, path: (403, "x", {}) if "OAI-SearchBot" in ua else None)
    try:
        assert _checklist_status(_run_live(base))["access"] == "issue"
    finally:
        server.shutdown()
    server, base, _ = _serve()
    try:
        assert _checklist_status(_run_live(base))["access"] == "ok"
    finally:
        server.shutdown()
    assert _checklist_status(_run("User-agent: ChatGPT-User\nDisallow: /\n"))["access"] == "issue"   # KIS-01


# ---- Nachbesserungen aus dem Review ----

def test_rate_limit_and_outage_statuses_are_not_a_bot_block():
    for status in (429, 503, 500):
        server, base, _ = _serve(lambda ua, path, status=status: (status, "x", {}) if "OAI-SearchBot" in ua else None)
        try:
            result = _run_live(base)
        finally:
            server.shutdown()
        assert _entry(result, "OAI-SearchBot")["server"] == "unknown", status
        assert not any(f["id"] == "KIS-03" for f in result["findings"]), status


def test_block_needs_a_normal_request_to_still_work():
    # Der Server lehnt Bots ab und gleichzeitig jede andere Anfrage nach der ersten (Ausfall, Drosselung): das ist keine Bot-Sperre.
    def rule(ua, path):
        if "site-auditor" in ua or any(bot in ua for bot in PROBED):
            return 403, "x", {}
        return None
    server, base, _ = _serve(rule)
    try:
        result = _run_live(base)
    finally:
        server.shutdown()
    assert all(c["server"] == "unknown" for c in result["crawlers"]) and not any(f["id"] == "KIS-03" for f in result["findings"])


def test_kis_03_severity_depends_on_how_many_bots_are_blocked():
    server, base, _ = _serve(lambda ua, path: (403, "x", {}) if "OAI-SearchBot" in ua or "ChatGPT-User" in ua else None)
    try:
        result = _run_live(base)
    finally:
        server.shutdown()
    f = next(f for f in result["findings"] if f["id"] == "KIS-03")
    assert f["severity"] == "HOCH" and "OAI-SearchBot" in f["finding"] and "ChatGPT-User" in f["finding"]
    assert "festen Adressen" in f["impact"] + f["solution"]   # echte Bots können trotzdem durchkommen


def test_prerendered_page_for_bots_is_not_a_js_only_page():
    shell = "<html><body><div id='app'></div></body></html>"
    rich = f"<html><body><h1>Titel</h1><p>{'wort ' * 280}</p></body></html>"
    server, base, _ = _serve(lambda ua, path: (200, rich, {}) if any(bot in ua for bot in PROBED) else (200, shell, {}))
    try:
        result = _run_live(base, html=shell)
    finally:
        server.shutdown()
    ai_visibility.apply_render_check(result, shell, _fv(300))
    assert result["render"]["html_words"] >= 280 and not any(f["id"] == "KIS-04" for f in result["findings"])


def test_noimageai_alone_is_listed_but_gives_no_finding():
    result = _analyze(_page("<h1>T</h1>"), {"X-Robots-Tag": "noimageai"})
    assert result["snippets"]["restricted"] == ["noimageai"] and "KIS-07" not in _ids(result)


def test_checklist_entity_does_not_claim_a_finding_that_does_not_exist():
    top = _analyze(_page("<h1>T</h1><h2>U</h2>", head=_ld({"@type": "Organization", "name": "M", "url": "https://x.de/"})))
    entry = next(c for c in top["checklist"] if c["key"] == "entity")
    assert entry["status"] == "unknown" and "Logo" in entry["detail"] and "KIS-06" not in _ids(top)
    graph = {"@graph": [{"@type": "Organization", "name": "M", "url": "https://x.de/"}]}
    assert next(c for c in _analyze(_page("<h1>T</h1>", head=_ld(graph)))["checklist"] if c["key"] == "entity")["status"] == "issue"


def test_person_schema_counts_as_entity_without_a_firm_finding():
    person = {"@type": "Person", "name": "Tobias", "image": "https://x.de/me.jpg", "sameAs": ["https://www.linkedin.com/in/x"]}
    result = _analyze(_page("<h1>T</h1>", head=_ld(person)))
    assert result["entity"]["organization"] is True and "KIS-06" not in _ids(result)
    assert next(c for c in result["checklist"] if c["key"] == "entity")["status"] == "ok"


def test_non_string_schema_types_do_not_break_the_module():
    weird = {"@type": [None, 5, "Organization"], "name": "x"}
    for data in (weird, {"@graph": [weird, {"@type": 7}]}, [None, {"@type": None}]):
        result = _analyze(_page("<h1>T</h1>", head=_ld(data)))
        assert "error" not in result and "crawlers" in result, data


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("test_ai_visibility: all tests passed")
