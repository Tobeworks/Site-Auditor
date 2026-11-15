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


def _run(body="<p>x</p>", head=HEAD, client=None, key="test-key"):
    reviews._PLACES_CACHE.clear()
    html = f"<html><head>{head}</head><body>{body}</body></html>"
    env = {"GOOGLE_PLACES_API_KEY": key} if key else {}
    with patch.dict(os.environ, env, clear=False), patch("httpx.Client", return_value=client or _client(GOOD)):
        if not key:
            os.environ.pop("GOOGLE_PLACES_API_KEY", None)
        return reviews.run(URL, html, BeautifulSoup(html, "lxml"), {})


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
    print("test_reviews_places: all tests passed")
