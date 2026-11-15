"""Tests für Teil B von auditor.checks.reviews (Google Places). Kein echter Aufruf.
Run: uv run python test/test_reviews_places.py"""
import json
import os
from unittest.mock import MagicMock, patch

import httpx
from bs4 import BeautifulSoup
from auditor.checks import reviews

URL = "https://x.de/"
GOOD = {"places": [{
    "displayName": {"text": "Muster GmbH"}, "formattedAddress": "Hauptstr. 1, 55116 Mainz, Deutschland",
    "nationalPhoneNumber": "06131 123456", "websiteUri": "https://www.x.de/", "rating": 4.8, "userRatingCount": 47,
}]}
LD = json.dumps({"@type": "LocalBusiness", "name": "Muster GmbH", "address": {"addressLocality": "Mainz"}})
HEAD = f'<script type="application/ld+json">{LD}</script>'


def _client(response=None, status=200, exc=None, bad_json=False):
    client = MagicMock()
    client.__enter__.return_value = client
    if exc is not None:
        client.post.side_effect = exc
    else:
        resp = MagicMock(status_code=status)
        if bad_json:
            resp.json.side_effect = ValueError("kein json")
        else:
            resp.json.return_value = response
        client.post.return_value = resp
    return client


BODY = "<p>" + "Wir bauen Websites für Unternehmen aus der Region und beraten persönlich. " * 3 + "</p>"


def _run(body=BODY, head=HEAD, client=None, key="test-key", url=URL):
    reviews._PLACES_CACHE.clear()
    html = f"<html><head>{head}</head><body>{body}</body></html>"
    env = {"GOOGLE_PLACES_API_KEY": key} if key else {}
    with patch.dict(os.environ, env, clear=False), patch("httpx.Client", return_value=client or _client(GOOD)):
        if not key:
            os.environ.pop("GOOGLE_PLACES_API_KEY", None)
        return reviews.run(url, html, BeautifulSoup(html, "lxml"), {})


def _ids(result):
    return {f["id"]: f for f in result["findings"]}


def test_without_api_key_is_disabled_and_makes_no_request():
    client = _client(GOOD)
    r = _run(client=client, key=None)
    assert r["google"]["status"] == "disabled"
    client.post.assert_not_called()


def test_match_requires_same_domain():
    other = {"places": [{**GOOD["places"][0], "websiteUri": "https://www.jameda.de/muster"}]}
    for uri in ("https://www.jameda.de/muster", "https://instagram.com/muster", "https://x.de.evil.com/"):
        other["places"][0]["websiteUri"] = uri
        r = _run(client=_client(other))
        assert r["google"]["status"] == "not_matched", uri
        assert r["google"]["rating"] is None


def test_www_is_ignored_when_matching():
    r = _run()
    assert r["google"]["status"] == "found"
    assert r["google"]["rating"] == 4.8 and r["google"]["count"] == 47
    assert r["google"]["name"] == "Muster GmbH"


def test_found_with_reviews_but_none_on_page_is_mittel_with_numbers():
    f = _ids(_run())["REV-02"]
    assert f["severity"] == "MITTEL"
    assert "4,8" in f["finding"] and "47" in f["finding"]
    assert "erkannt" in f["finding"]   # nur eine Aussage über das, was erkannt wurde


def test_found_and_shown_on_page_is_positive():
    r = _run(body="<h2>Kundenstimmen</h2>")
    assert _ids(r)["REV-02"]["severity"] == "POSITIV"


def test_not_matched_has_no_finding():
    r = _run(client=_client({"places": []}))
    assert r["google"]["status"] == "not_matched"
    assert not any(f["id"] in ("REV-02", "REV-03", "REV-04") for f in r["findings"])


def test_provider_errors_never_raise():
    cases = [
        _client(status=401), _client(status=402), _client(status=429),
        _client(exc=httpx.TimeoutException("timeout")), _client(bad_json=True), _client(response={"places": "kaputt"}),
    ]
    for client in cases:
        r = _run(client=client)
        assert r["google"]["status"] == "error"
        assert not any(f["id"] in ("REV-02", "REV-03", "REV-04") for f in r["findings"])


def test_second_call_for_same_domain_uses_cache():
    client = _client(GOOD)
    reviews._PLACES_CACHE.clear()
    html = f"<html><head>{HEAD}</head><body><p>x</p></body></html>"
    with patch.dict(os.environ, {"GOOGLE_PLACES_API_KEY": "k"}), patch("httpx.Client", return_value=client):
        reviews.run(URL, html, BeautifulSoup(html, "lxml"), {})
        reviews.run(URL, html, BeautifulSoup(html, "lxml"), {})
    assert client.post.call_count == 1


def test_request_uses_key_field_mask_and_name_with_locality():
    client = _client(GOOD)
    _run(client=client)
    kwargs = client.post.call_args.kwargs
    assert kwargs["headers"]["X-Goog-Api-Key"] == "test-key"
    assert "places.userRatingCount" in kwargs["headers"]["X-Goog-FieldMask"]
    assert kwargs["json"]["textQuery"] == "Muster GmbH Mainz"


def test_phone_mismatch_is_reported_only_when_page_has_a_phone():
    mismatch = _ids(_run(body="<p>Tel. 06131 999999</p>"))
    assert mismatch["REV-03"]["severity"] == "MITTEL"
    assert "06131 999999" in mismatch["REV-03"]["finding"] and "06131 123456" in mismatch["REV-03"]["finding"]
    assert "REV-03" not in _ids(_run(body="<p>kein Telefon</p>"))


def test_phone_formats_are_normalized():
    for text in ("+49 6131 123456", "+49 (0) 6131 123456", "0049 6131 123456", "06131/123456"):
        assert "REV-03" not in _ids(_run(body=f"<p>Telefon {text}</p>")), text


def test_address_mismatch_compares_postcode():
    assert _ids(_run(body="<p>Musterweg 3, 55124 Mainz</p>"))["REV-04"]["severity"] == "MITTEL"
    assert "REV-04" not in _ids(_run(body="<p>Hauptstr. 1, 55116 Mainz</p>"))
    assert "REV-04" not in _ids(_run(body="<p>Keine Adresse hier</p>"))


def test_js_shell_page_gets_no_negative_finding():
    r = _run(body='<div id="app"></div><script src="/app.js"></script>')
    assert r["google"]["status"] == "found"
    assert "REV-02" not in _ids(r)


def test_unknown_review_wording_prevents_negative_finding():
    text = "Erfahrungen unserer Gäste ★★★★★ " + "Wir bauen Websites für Unternehmen aus der Region. " * 3
    assert "REV-02" not in _ids(_run(body=f"<p>{text}</p>"))
    assert "REV-02" not in _ids(_run(body=BODY + '<a href="/referenzen/">Mehr</a>'))
    assert "REV-02" not in _ids(_run(body=BODY + '<img src="a.png" alt="5 Sterne Bewertung">'))


def test_schema_with_text_hint_has_no_negative_finding():
    ld = json.dumps({"@type": "LocalBusiness", "aggregateRating": {"ratingValue": 5, "reviewCount": 3}})
    head = f'<script type="application/ld+json">{ld}</script>'
    assert "REV-01" not in _ids(_run(body="<h2>Erfahrungen</h2><p>★★★★★ sehr gut</p>", head=head, key=None))
    assert _ids(_run(body=BODY, head=head, key=None))["REV-01"]["severity"] == "MITTEL"


def test_two_places_with_the_same_domain_are_ambiguous():
    second = {**GOOD["places"][0], "formattedAddress": "Domstr. 5, 50667 Köln", "rating": 3.1}
    r = _run(client=_client({"places": [GOOD["places"][0], second]}))
    assert r["google"]["status"] == "not_matched"


def test_path_must_match_for_shared_hosts():
    foreign = {"places": [{**GOOD["places"][0], "websiteUri": "https://facebook.com/anderefirma", "rating": 1.2}]}
    r = _run(client=_client(foreign), url="https://facebook.com/meinefirma", head="")
    assert r["google"]["status"] == "not_matched" and r["google"]["rating"] is None
    same = {"places": [{**GOOD["places"][0], "websiteUri": "https://facebook.com/meinefirma"}]}
    assert _run(client=_client(same), url="https://facebook.com/meinefirma", head="")["google"]["status"] == "found"


def test_foreign_phone_formats_are_not_compared():
    assert "REV-03" not in _ids(_run(body='<a href="tel:+4312345678">anrufen</a>', client=_client({"places": [{**GOOD["places"][0], "nationalPhoneNumber": "01 2345678"}]})))


def test_percent_encoded_tel_link_is_decoded():
    assert "REV-03" not in _ids(_run(body='<a href="tel:+49%206131%20123456">anrufen</a>'))


def test_unlabeled_numbers_and_opening_hours_are_not_phone_numbers():
    body = "<p>Mo-Fr 09-12 / 14-18 Uhr, Steuernummer 026 123 45678</p>"
    assert "REV-03" not in _ids(_run(body=body))


def test_postcode_only_from_street_addresses_not_from_any_number():
    assert "REV-04" not in _ids(_run(body="<p>Schon 15000 Kunden vertrauen uns.</p>"))
    assert "REV-04" not in _ids(_run(body="<p>Postfach 1234, 55001 Mainz</p>"))
    ld = json.dumps({"@type": "LocalBusiness", "name": "Muster GmbH", "address": {"addressLocality": "Mainz", "postalCode": "55124"}})
    r = _run(body="<p>x</p>", head=f'<script type="application/ld+json">{ld}</script>')
    assert _ids(r)["REV-04"]["severity"] == "MITTEL"


if __name__ == "__main__":
    test_without_api_key_is_disabled_and_makes_no_request()
    test_match_requires_same_domain()
    test_www_is_ignored_when_matching()
    test_found_with_reviews_but_none_on_page_is_mittel_with_numbers()
    test_found_and_shown_on_page_is_positive()
    test_not_matched_has_no_finding()
    test_provider_errors_never_raise()
    test_second_call_for_same_domain_uses_cache()
    test_request_uses_key_field_mask_and_name_with_locality()
    test_phone_mismatch_is_reported_only_when_page_has_a_phone()
    test_phone_formats_are_normalized()
    test_address_mismatch_compares_postcode()
    test_js_shell_page_gets_no_negative_finding()
    test_unknown_review_wording_prevents_negative_finding()
    test_schema_with_text_hint_has_no_negative_finding()
    test_two_places_with_the_same_domain_are_ambiguous()
    test_path_must_match_for_shared_hosts()
    test_foreign_phone_formats_are_not_compared()
    test_percent_encoded_tel_link_is_decoded()
    test_unlabeled_numbers_and_opening_hours_are_not_phone_numbers()
    test_postcode_only_from_street_addresses_not_from_any_number()
    print("test_reviews_places: all tests passed")
