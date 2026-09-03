"""Assert-based smoke test for auditor.checks.structured_data. Run: uv run python test/test_structured_data.py"""
import json
from bs4 import BeautifulSoup
from auditor.checks import structured_data


def _page(json_ld_objects, body_extra=""):
    scripts = "\n".join(
        f'<script type="application/ld+json">{json.dumps(o)}</script>' for o in json_ld_objects
    )
    html = f"<html><head>{scripts}</head><body>{body_extra}</body></html>"
    return html, BeautifulSoup(html, "lxml")


def test_no_jsonld_is_hoch():
    html, soup = _page([])
    result = structured_data.run("https://x.de", html, soup, {})
    f = next(f for f in result["findings"] if f["id"] == "SDA-02")
    assert f["severity"] == "HOCH"


def test_missing_required_field_is_mittel():
    html, soup = _page([{"@type": "Product", "name": "Schraube"}])  # offers missing
    result = structured_data.run("https://x.de", html, soup, {})
    f = next(f for f in result["findings"] if f["id"] == "SDA-03")
    assert f["severity"] == "MITTEL"
    assert "offers" in f["finding"]


def test_price_mismatch_is_hoch():
    html, soup = _page(
        [{"@type": "Product", "name": "Schraube", "offers": {"price": "9.99"}}],
        body_extra="<p>Jetzt kaufen für 19,99 €</p>",
    )
    result = structured_data.run("https://x.de", html, soup, {})
    f = next(f for f in result["findings"] if f["id"] == "SDA-07")
    assert f["severity"] == "HOCH"


def test_price_match_is_positiv():
    html, soup = _page(
        [{"@type": "Product", "name": "Schraube", "offers": {"price": "19.99"}}],
        body_extra="<p>Jetzt kaufen für 19,99 €</p>",
    )
    result = structured_data.run("https://x.de", html, soup, {})
    f = next(f for f in result["findings"] if f["id"] == "SDA-07")
    assert f["severity"] == "POSITIV"
    assert f["solution"] is None


def test_visible_breadcrumb_without_schema_is_mittel():
    html, soup = _page(
        [{"@type": "WebSite", "name": "x", "url": "https://x.de"}],
        body_extra='<nav class="breadcrumbs">Start &gt; Kategorie</nav>',
    )
    result = structured_data.run("https://x.de", html, soup, {})
    f = next(f for f in result["findings"] if f["id"] == "SDA-08")
    assert f["severity"] == "MITTEL"


def test_malformed_jsonld_produces_finding():
    html = '<html><head><script type="application/ld+json">{not valid json</script></head><body></body></html>'
    soup = BeautifulSoup(html, "lxml")
    result = structured_data.run("https://x.de", html, soup, {})
    f = next(f for f in result["findings"] if f["id"] == "SDA-01")
    assert f["severity"] == "MITTEL"


if __name__ == "__main__":
    test_no_jsonld_is_hoch()
    test_missing_required_field_is_mittel()
    test_price_mismatch_is_hoch()
    test_price_match_is_positiv()
    test_visible_breadcrumb_without_schema_is_mittel()
    test_malformed_jsonld_produces_finding()
    print("test_structured_data: all tests passed")
