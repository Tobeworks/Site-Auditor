"""Assert-based smoke test for auditor.checks.a11y. Run: uv run python test/test_a11y.py"""
from unittest.mock import patch
from bs4 import BeautifulSoup
from auditor.checks import a11y


def test_images_without_alt_is_mittel():
    html = '<html lang="de"><body><img src="x.jpg"></body></html>'
    soup = BeautifulSoup(html, "lxml")
    with patch.object(a11y, "_run_axe", return_value={"violations": [], "incomplete": []}):
        result = a11y.run("https://x.de", html, soup, {})
    f = next(f for f in result["findings"] if f["id"] == "A11-03")
    assert f["severity"] == "MITTEL"


def test_missing_lang_attribute_is_mittel():
    html = "<html><body><img src=\"x.jpg\" alt=\"ok\"></body></html>"
    soup = BeautifulSoup(html, "lxml")
    with patch.object(a11y, "_run_axe", return_value={"violations": [], "incomplete": []}):
        result = a11y.run("https://x.de", html, soup, {})
    f = next(f for f in result["findings"] if f["id"] == "A11-08")
    assert f["severity"] == "MITTEL"


def test_clean_page_has_positiv_findings():
    html = '<html lang="de"><body><img src="x.jpg" alt="ok"><a href="/x">Startseite besuchen</a></body></html>'
    soup = BeautifulSoup(html, "lxml")
    with patch.object(a11y, "_run_axe", return_value={"violations": [], "incomplete": []}):
        result = a11y.run("https://x.de", html, soup, {})
    ids = {f["id"]: f["severity"] for f in result["findings"]}
    assert ids["A11-03"] == "POSITIV"
    assert ids["A11-08"] == "POSITIV"
    assert "issues" not in result


def test_error_path_returns_error_key():
    with patch.object(a11y, "_run_axe", side_effect=RuntimeError("boom")):
        result = a11y.run("https://x.de", "<html></html>", BeautifulSoup("", "lxml"), {})
    assert "error" in result


def test_prefetched_axe_results_are_used_without_own_browser():
    html = '<html lang="de"><body><img src="x.jpg" alt="ok"></body></html>'
    axe = {"violations": [{"id": "color-contrast", "impact": "serious", "tags": ["wcag2aa"], "description": "d", "nodes": [{"target": ["p"]}]}], "incomplete": []}
    with patch.object(a11y, "_run_axe", side_effect=AssertionError("kein eigener Browser")):
        result = a11y.run("https://x.de", html, BeautifulSoup(html, "lxml"), {}, axe_results=axe, own_browser=False)
    assert next(f for f in result["findings"] if f["id"] == "A11-02")["severity"] == "HOCH"


def test_missing_axe_results_without_own_browser_is_an_error_not_an_unprotected_visit():
    with patch.object(a11y, "_run_axe", side_effect=AssertionError("kein eigener Browser")):
        result = a11y.run("https://x.de", "<html></html>", BeautifulSoup("", "lxml"), {}, axe_results=None, own_browser=False)
    assert "error" in result


def _img_count(html):
    with patch.object(a11y, "_run_axe", return_value={"violations": [], "incomplete": []}):
        result = a11y.run("https://x.de", html, BeautifulSoup(html, "lxml"), {})
    return result["manual_checks"]["images_without_alt"]


def test_empty_alt_in_a_link_with_text_is_a_decorative_image_not_a_finding():
    assert _img_count('<html lang="de"><body><a href="/x"><img src="a.jpg" alt=""><h3>Titel des Artikels</h3></a></body></html>') == 0


def test_empty_alt_as_only_content_of_a_link_is_a_finding():
    assert _img_count('<html lang="de"><body><a href="/x"><img src="a.jpg" alt=""></a></body></html>') == 1


def test_role_presentation_without_alt_is_decorative():
    assert _img_count('<html lang="de"><body><img src="a.jpg" role="presentation"></body></html>') == 0


if __name__ == "__main__":
    test_images_without_alt_is_mittel()
    test_missing_lang_attribute_is_mittel()
    test_clean_page_has_positiv_findings()
    test_error_path_returns_error_key()
    print("test_a11y: all tests passed")
