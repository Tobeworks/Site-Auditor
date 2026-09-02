"""Assert-based smoke test for auditor.checks.content_quality. Run: uv run python test_content_quality.py"""
from unittest.mock import patch, MagicMock
from bs4 import BeautifulSoup
from auditor.checks import content_quality

LONG_TEXT = " ".join(["Wort"] * 350)
HTML = f"<html><head><title>Seite</title></head><body><h1>Andere Überschrift</h1><p>{LONG_TEXT}</p></body></html>"


def _soft_404_response(status_code, body="<html><body>Generic error</body></html>"):
    r = MagicMock()
    r.status_code = status_code
    r.text = body
    return r


def test_thin_content_is_mittel():
    html = "<html><head><title>x</title></head><body><h1>x</h1><p>Kurzer Text.</p></body></html>"
    soup = BeautifulSoup(html, "lxml")
    with patch("httpx.get", return_value=_soft_404_response(404)):
        result = content_quality.run("https://x.de", html, soup, {})
    f = next(f for f in result["findings"] if f["id"] == "CNT-01")
    assert f["severity"] == "MITTEL"


def test_sufficient_content_is_positiv():
    soup = BeautifulSoup(HTML, "lxml")
    with patch("httpx.get", return_value=_soft_404_response(404)):
        result = content_quality.run("https://x.de", HTML, soup, {})
    f = next(f for f in result["findings"] if f["id"] == "CNT-01")
    assert f["severity"] == "POSITIV"


def test_soft_404_returning_200_is_hoch():
    soup = BeautifulSoup(HTML, "lxml")
    with patch("httpx.get", return_value=_soft_404_response(200, "<html><body>Found it</body></html>")):
        result = content_quality.run("https://x.de", HTML, soup, {})
    f = next(f for f in result["findings"] if f["id"] == "CNT-05")
    assert f["severity"] == "HOCH"


def test_generic_404_page_is_mittel():
    soup = BeautifulSoup(HTML, "lxml")
    with patch("httpx.get", return_value=_soft_404_response(404, "<html><body>Not Found</body></html>")):
        result = content_quality.run("https://x.de", HTML, soup, {})
    f = next(f for f in result["findings"] if f["id"] == "CNT-05")
    assert f["severity"] == "MITTEL"


def test_error_path_returns_error_key():
    class BoomSoup:
        def __call__(self, *a, **k):
            raise RuntimeError("boom")
        def get_text(self, *a, **k):
            raise RuntimeError("boom")
    result = content_quality.run("https://x.de", "<html></html>", BoomSoup(), {})
    assert "error" in result


if __name__ == "__main__":
    test_thin_content_is_mittel()
    test_sufficient_content_is_positiv()
    test_soft_404_returning_200_is_hoch()
    test_generic_404_page_is_mittel()
    test_error_path_returns_error_key()
    print("test_content_quality: all tests passed")
