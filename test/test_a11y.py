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


if __name__ == "__main__":
    test_images_without_alt_is_mittel()
    test_missing_lang_attribute_is_mittel()
    test_clean_page_has_positiv_findings()
    test_error_path_returns_error_key()
    print("test_a11y: all tests passed")
