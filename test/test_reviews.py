"""Assert-based smoke test for auditor.checks.reviews. Run: uv run python test/test_reviews.py"""
import json
import os
from unittest.mock import patch
from bs4 import BeautifulSoup
from auditor.checks import reviews

os.environ.pop("GOOGLE_PLACES_API_KEY", None)  # Teil A läuft ohne Zugang


def _run(body: str, head: str = ""):
    html = f"<html><head>{head}</head><body>{body}</body></html>"
    with patch("httpx.Client", side_effect=AssertionError("Teil A darf nichts abrufen")):
        return reviews.run("https://x.de/", html, BeautifulSoup(html, "lxml"), {})


def _ld(data: dict) -> str:
    return f'<script type="application/ld+json">{json.dumps(data)}</script>'


def _negative(result):
    return [f for f in result["findings"] if f["severity"] != "POSITIV"]


def test_schema_aggregate_rating_detected():
    r = _run("<p>x</p>", _ld({"@type": "LocalBusiness", "aggregateRating": {"@type": "AggregateRating", "ratingValue": 4.8, "reviewCount": 12}}))
    assert r["schema_reviews"] is True


def test_schema_review_in_graph_detected():
    r = _run("<p>x</p>", _ld({"@graph": [{"@type": "Organization"}, {"@type": "Review", "reviewBody": "gut"}]}))
    assert r["schema_reviews"] is True


def test_microdata_aggregate_rating_detected():
    r = _run('<div itemscope itemtype="https://schema.org/LocalBusiness"><span itemprop="aggregateRating">4,8</span></div>')
    assert r["schema_reviews"] is True


def test_broken_json_ld_is_ignored():
    r = _run("<p>x</p>", '<script type="application/ld+json">{kaputt</script>')
    assert r["schema_reviews"] is False


def test_known_widgets_detected_by_script_src():
    cases = {
        "Trustindex": "https://cdn.trustindex.io/loader.js",
        "Elfsight": "https://static.elfsight.com/platform/platform.js",
        "EmbedSocial": "https://embedsocial.com/cdn/ri.js",
        "Trustpilot": "https://widget.trustpilot.com/bootstrap/v5/tp.widget.bootstrap.min.js",
        "ProvenExpert": "https://www.provenexpert.com/widget/x.js",
    }
    for name, src in cases.items():
        r = _run(f'<p>x</p><script src="{src}"></script>')
        assert name in r["widgets"], name


def test_google_review_link_detected():
    for href in ("https://g.page/r/abc/review", "https://www.google.com/maps/place/Firma",
                 "https://search.google.com/local/reviews?placeid=x"):
        assert _run(f'<a href="{href}">Bewerten</a>')["google_link"] is True, href


def test_testimonial_heading_detected():
    for text in ("Kundenstimmen", "Das sagen unsere Kunden", "Bewertungen", "Referenzen", "Testimonials"):
        assert _run(f"<h2>{text}</h2>")["testimonial_section"] is True, text


def test_page_without_any_signal_has_no_negative_finding():
    r = _run("<h1>Willkommen</h1><p>Wir bauen Websites.</p>")
    assert r["schema_reviews"] is False and r["widgets"] == [] and r["google_link"] is False
    assert r["testimonial_section"] is False
    assert r["findings"] == []


def test_schema_without_visible_reviews_is_mittel():
    r = _run("<p>x</p>", _ld({"@type": "LocalBusiness", "aggregateRating": {"ratingValue": 5, "reviewCount": 3}}))
    f = next(f for f in r["findings"] if f["id"] == "REV-01")
    assert f["severity"] == "MITTEL"


def test_schema_with_visible_reviews_has_no_negative_finding():
    r = _run("<h2>Kundenstimmen</h2>", _ld({"@type": "LocalBusiness", "aggregateRating": {"ratingValue": 5, "reviewCount": 3}}))
    assert _negative(r) == []


def test_widget_without_schema_gets_positive_hint_only():
    r = _run('<p>x</p><script src="https://cdn.trustindex.io/loader.js"></script>')
    assert any(f["id"] == "REV-05" and f["severity"] == "POSITIV" for f in r["findings"])
    assert _negative(r) == []


def test_google_part_is_disabled_without_matching_data():
    r = _run("<p>x</p>")
    assert r["google"]["status"] == "disabled"


def test_error_path_returns_error_key():
    class BoomSoup:
        def find_all(self, *a, **k):
            raise RuntimeError("boom")
        find = find_all
    result = reviews.run("https://x.de/", "<html></html>", BoomSoup(), {})
    assert "error" in result


if __name__ == "__main__":
    test_schema_aggregate_rating_detected()
    test_schema_review_in_graph_detected()
    test_microdata_aggregate_rating_detected()
    test_broken_json_ld_is_ignored()
    test_known_widgets_detected_by_script_src()
    test_google_review_link_detected()
    test_testimonial_heading_detected()
    test_page_without_any_signal_has_no_negative_finding()
    test_schema_without_visible_reviews_is_mittel()
    test_schema_with_visible_reviews_has_no_negative_finding()
    test_widget_without_schema_gets_positive_hint_only()
    test_google_part_is_disabled_without_matching_data()
    test_error_path_returns_error_key()
    print("test_reviews: all tests passed")
