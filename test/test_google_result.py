"""Tests für auditor.checks.google_result (DataForSEO). Kein echter Aufruf.
Run: uv run python test/test_google_result.py"""
import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
from bs4 import BeautifulSoup
from auditor.checks import google_result

FIXTURE = Path(__file__).parent / "fixtures" / "google_result_no_domain_hit.json"
META = "Wir bauen Websites für Unternehmen aus Mainz, schnell, sicher und mit direktem Ansprechpartner. Von der Idee bis zum Betrieb."  # über 120 Zeichen


def _item(host, title="Titel", description="Text", links=None, name=None, path=""):
    return {"type": "organic", "title": title, "description": description, "breadcrumb": f"https://{host}{path}",
            "website_name": name or host, "url": "https://google.com/goto?url=x", "links": links}


def _resp(items, task_status=20000):
    return {"status_code": 20000, "tasks": [{"status_code": task_status, "result": [{"items": items}]}]}


def _client(payload=None, status=200, exc=None, bad_json=False):
    client = MagicMock()
    client.__enter__.return_value = client
    if exc is not None:
        client.post.side_effect = exc
    else:
        resp = MagicMock(status_code=status)
        if bad_json:
            resp.json.side_effect = ValueError("kein json")
        else:
            resp.json.return_value = payload
        client.post.return_value = resp
    return client


def _fetch(payload=None, client=None, key="k"):
    google_result._GOOGLE_CACHE.clear()
    with patch.dict(os.environ, {"DATAFORSEO_API_KEY": key} if key else {}), patch("httpx.Client", return_value=client or _client(payload)):
        if not key:
            os.environ.pop("DATAFORSEO_API_KEY", None)
        return google_result.fetch_google_result("x.de")


def _run(payload, head="", key="k", url="https://www.x.de/"):
    google_result._GOOGLE_CACHE.clear()
    html = f"<html><head>{head}</head><body><p>x</p></body></html>"
    with patch.dict(os.environ, {"DATAFORSEO_API_KEY": key}), patch("httpx.Client", return_value=_client(payload)):
        return google_result.run(url, html, BeautifulSoup(html, "lxml"), {})


def _by_id(result):
    return {f["id"]: f for f in result["findings"]}


def test_picks_first_organic_result_of_the_domain():
    r = _fetch(_resp([_item("wikipedia.org"), _item("www.x.de", "Erster", "Text eins"), _item("x.de", "Zweiter", "Text zwei")]))
    assert r["status"] == "found"
    assert r["title"] == "Erster" and r["description"] == "Text eins"
    assert r["display_url"] == "https://www.x.de"
    assert r["query"] == "x.de" and r["fetched_at"].endswith("Z") or "+00:00" in r["fetched_at"]


def test_other_domains_are_ignored():
    for host in ("wikipedia.org", "x.de.evil.com", "notx.de", "jameda.de"):
        assert _fetch(_resp([_item(host)]))["status"] == "not_found", host


def test_subpage_hit_is_not_a_match():
    # Eine Unterseite hat eine andere Beschreibung als die Startseite, der Vergleich wäre ein Fehlalarm.
    r = _fetch(_resp([_item("x.de", "Insights", "Artikel", path=" › insights")]))
    assert r["status"] == "not_found" and r["title"] is None


def test_homepage_hit_after_a_subpage_hit_is_used():
    r = _fetch(_resp([_item("x.de", "Insights", "Artikel", path=" › insights"), _item("x.de", "Start", "Willkommen")]))
    assert r["status"] == "found" and r["title"] == "Start"


def test_real_response_without_domain_hit_is_not_found():
    payload = json.loads(FIXTURE.read_text())
    r = _fetch(payload)
    assert r["status"] == "not_found"
    assert r["title"] is None and r["sitelinks"] == []


def test_url_field_with_google_redirect_does_not_count_as_a_hit():
    item = _item("wikipedia.org")
    item["breadcrumb"] = None
    assert _fetch(_resp([item]))["status"] == "not_found"


def test_sitelinks_are_extracted_when_present_and_empty_otherwise():
    links = [{"type": "sitelink", "title": "Über uns", "description": "Wer wir sind"}, {"title": "Kontakt"}]
    r = _fetch(_resp([_item("x.de", links=links)]))
    assert r["sitelinks"] == [{"title": "Über uns", "description": "Wer wir sind"}, {"title": "Kontakt", "description": None}]
    assert _fetch(_resp([_item("x.de", links=None)]))["sitelinks"] == []


def test_without_api_key_is_disabled_and_makes_no_request():
    client = _client(_resp([]))
    assert _fetch(client=client, key=None)["status"] == "disabled"
    client.post.assert_not_called()


def test_provider_errors_never_raise():
    cases = [
        _client(status=401), _client(status=402), _client(exc=httpx.TimeoutException("timeout")),
        _client(bad_json=True), _client(_resp([_item("x.de")], task_status=40200)),   # 40200: Guthaben leer
        _client({"tasks": "kaputt"}),
    ]
    for client in cases:
        assert _fetch(client=client)["status"] == "error"


def test_second_call_for_same_domain_uses_cache():
    client = _client(_resp([_item("x.de")]))
    google_result._GOOGLE_CACHE.clear()
    with patch.dict(os.environ, {"DATAFORSEO_API_KEY": "k"}), patch("httpx.Client", return_value=client):
        google_result.fetch_google_result("x.de")
        google_result.fetch_google_result("x.de")
    assert client.post.call_count == 1


def test_request_uses_basic_auth_and_germany_desktop():
    client = _client(_resp([_item("x.de")]))
    _fetch(client=client, key="abc==")
    kwargs = client.post.call_args.kwargs
    assert kwargs["headers"]["Authorization"] == "Basic abc=="
    body = kwargs["json"][0]
    assert body["keyword"] == "x.de" and body["location_code"] == 2276 and body["language_code"] == "de" and body["device"] == "desktop"


def test_google_ignoring_meta_description_is_mittel():
    head = f'<meta name="description" content="{META}"><title>Muster GmbH Webdesign Mainz</title>'
    r = _run(_resp([_item("x.de", "Muster GmbH Webdesign Mainz", "Mainz – Zentrale Lage und lange Öffnungszeiten für Kunden …")]), head)
    f = _by_id(r)["GOO-01"]
    assert f["severity"] == "MITTEL"
    assert "Zentrale Lage" in f["impact"] and META[:30] in f["impact"]


def test_same_description_is_positive_even_when_google_cuts_it_off():
    head = f'<meta name="description" content="{META}">'
    r = _run(_resp([_item("x.de", "T", META[:80] + " …")]), head)
    assert _by_id(r)["GOO-01"]["severity"] == "POSITIV"


def test_short_description_already_reported_by_seo02_gives_no_second_finding():
    head = '<meta name="description" content="Flugzeugcharter und SEP Ratings für ATPL Piloten.">'
    r = _run(_resp([_item("x.de", "T", "Egelsbach – Zentrale Lage & maximale Flexibilität …")]), head)
    assert "GOO-01" not in _by_id(r)


def test_missing_meta_description_gives_no_finding():
    r = _run(_resp([_item("x.de", "T", "Irgendein Text")]))
    assert "GOO-01" not in _by_id(r)


def test_title_changed_by_google_is_mittel():
    r = _run(_resp([_item("x.de", "4Aviators Charter & Training", "Text")]), "<title>Startseite</title>")
    f = _by_id(r)["GOO-02"]
    assert f["severity"] == "MITTEL" and "4Aviators" in f["finding"]


def test_similar_title_is_no_finding():
    r = _run(_resp([_item("x.de", "Muster GmbH | Webdesign aus Mainz", "Text")]), "<title>Muster GmbH Webdesign Mainz</title>")
    assert "GOO-02" not in _by_id(r)


def test_checked_subpage_is_not_compared_with_the_homepage_hit():
    # Die Abfrage nach der Domain liefert die Startseite. Deren Text ist nicht der Text der geprüften Unterseite.
    head = f'<meta name="description" content="{META}"><title>Leistungen</title>'
    r = _run(_resp([_item("x.de", "Ganz anderer Titel", "Ganz anderer Text über etwas völlig anderes hier")]), head, url="https://www.x.de/leistungen/")
    assert r["status"] == "found" and r["findings"] == []
    r = _run(_resp([_item("x.de", "Ganz anderer Titel", "Ganz anderer Text über etwas völlig anderes hier")]), head, url="https://www.x.de/")
    assert {"GOO-01", "GOO-02"} <= set(_by_id(r))


def test_run_without_hit_or_key_has_no_findings_and_never_raises():
    assert _run(_resp([]), "")["findings"] == []
    google_result._GOOGLE_CACHE.clear()
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("DATAFORSEO_API_KEY", None)
        html = "<html></html>"
        r = google_result.run("https://x.de/", html, BeautifulSoup(html, "lxml"), {})
    assert r["status"] == "disabled" and r["findings"] == []


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("test_google_result: all tests passed")
