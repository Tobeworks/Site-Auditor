"""Assert-based smoke test for auditor.checks.legal. Run: uv run python test/test_legal.py"""
from unittest.mock import patch, MagicMock
from bs4 import BeautifulSoup
from auditor.checks import legal


def _client_mock(status=404):
    client = MagicMock()
    client.__enter__.return_value = client
    client.head.return_value = MagicMock(status_code=status)
    return client


def test_missing_impressum_is_hoch():
    html = "<html><body></body></html>"
    soup = BeautifulSoup(html, "lxml")
    with patch("httpx.Client", return_value=_client_mock(404)):
        result = legal.run("https://x.de", html, soup, {})
    f = next(f for f in result["findings"] if f["id"] == "LGL-01")
    assert f["severity"] == "HOCH"


def test_tracking_without_banner_is_hoch():
    html = "<html><body><script>gtag('config', 'x')</script></body></html>"
    soup = BeautifulSoup(html, "lxml")
    with patch("httpx.Client", return_value=_client_mock(404)):
        result = legal.run("https://x.de", html, soup, {})
    f = next(f for f in result["findings"] if f["id"] == "LGL-03")
    assert f["severity"] == "HOCH"


def test_tracking_with_banner_is_mittel():
    html = '<html><body><div class="cookiebot"></div><script>gtag(\'config\', \'x\')</script></body></html>'
    soup = BeautifulSoup(html, "lxml")
    with patch("httpx.Client", return_value=_client_mock(404)):
        result = legal.run("https://x.de", html, soup, {})
    f = next(f for f in result["findings"] if f["id"] == "LGL-03")
    assert f["severity"] == "MITTEL"


def test_error_path_returns_error_key():
    class BoomSoup:
        def find_all(self, *a, **k):
            raise RuntimeError("boom")
    result = legal.run("https://x.de", "<html></html>", BoomSoup(), {})
    assert "error" in result


if __name__ == "__main__":
    test_missing_impressum_is_hoch()
    test_tracking_without_banner_is_hoch()
    test_tracking_with_banner_is_mittel()
    test_error_path_returns_error_key()
    print("test_legal: all tests passed")
