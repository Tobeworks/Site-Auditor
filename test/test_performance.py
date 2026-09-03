"""Assert-based smoke test for auditor.checks.performance. Run: uv run python test_performance.py"""
from unittest.mock import patch, MagicMock
from bs4 import BeautifulSoup
from auditor.checks import performance


def _headers(**overrides):
    base = {"_http_version": "HTTP/2", "content-encoding": "br", "cache-control": "public, max-age=3600"}
    base.update(overrides)
    return base


def test_no_compression_is_mittel():
    with patch("shutil.which", return_value=None), \
         patch("httpx.Client") as mock_client:
        mock_client.return_value.__enter__.return_value.head.return_value = MagicMock(status_code=404, headers={})
        result = performance.run("https://x.de", "<html></html>", BeautifulSoup("", "lxml"), _headers(**{"content-encoding": ""}))
    f = next(f for f in result["findings"] if f["id"] == "PRF-01")
    assert f["severity"] == "MITTEL"


def test_http1_is_mittel_http2_is_positiv():
    with patch("shutil.which", return_value=None), \
         patch("httpx.Client") as mock_client:
        mock_client.return_value.__enter__.return_value.head.return_value = MagicMock(status_code=404, headers={})
        result = performance.run("https://x.de", "<html></html>", BeautifulSoup("", "lxml"), _headers(**{"_http_version": "HTTP/1.1"}))
        f = next(f for f in result["findings"] if f["id"] == "PRF-05")
        assert f["severity"] == "MITTEL"

        result2 = performance.run("https://x.de", "<html></html>", BeautifulSoup("", "lxml"), _headers())
        f2 = next(f for f in result2["findings"] if f["id"] == "PRF-05")
        assert f2["severity"] == "POSITIV"


def test_no_store_html_cache_control_is_mittel():
    with patch("shutil.which", return_value=None), \
         patch("httpx.Client") as mock_client:
        mock_client.return_value.__enter__.return_value.head.return_value = MagicMock(status_code=404, headers={})
        result = performance.run("https://x.de", "<html></html>", BeautifulSoup("", "lxml"), _headers(**{"cache-control": "no-store"}))
    f = next(f for f in result["findings"] if f["id"] == "PRF-02")
    assert f["severity"] == "MITTEL"


def test_duplicate_jquery_versions_is_hoch():
    html = '<script src="/js/jquery-1.12.4.min.js"></script><script src="/js/jquery-3.6.0.min.js"></script>'
    soup = BeautifulSoup(f"<html><head>{html}</head></html>", "lxml")
    with patch("shutil.which", return_value=None), \
         patch("httpx.Client") as mock_client:
        mock_client.return_value.__enter__.return_value.head.return_value = MagicMock(status_code=404, headers={})
        result = performance.run("https://x.de", html, soup, _headers())
    f = next(f for f in result["findings"] if f["id"] == "PRF-14")
    assert f["severity"] == "HOCH"


def test_font_awesome_full_include_is_mittel():
    html = '<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">'
    soup = BeautifulSoup(f"<html><head>{html}</head></html>", "lxml")
    with patch("shutil.which", return_value=None), \
         patch("httpx.Client") as mock_client:
        mock_client.return_value.__enter__.return_value.head.return_value = MagicMock(status_code=200, headers={"content-length": "80000"})
        result = performance.run("https://x.de", html, soup, _headers())
    f = next(f for f in result["findings"] if f["id"] == "PRF-16")
    assert f["severity"] == "MITTEL"
    assert result["icon_font_detected"] is True


def test_error_path_returns_error_key():
    class BoomSoup:
        def find(self, *a, **k):
            raise RuntimeError("boom")
        def find_all(self, *a, **k):
            raise RuntimeError("boom")
    result = performance.run("https://x.de", "<html></html>", BoomSoup(), {})
    assert "error" in result


if __name__ == "__main__":
    test_no_compression_is_mittel()
    test_http1_is_mittel_http2_is_positiv()
    test_no_store_html_cache_control_is_mittel()
    test_duplicate_jquery_versions_is_hoch()
    test_font_awesome_full_include_is_mittel()
    test_error_path_returns_error_key()
    print("test_performance: all tests passed")
