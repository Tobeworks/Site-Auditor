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


def test_no_tracking_means_consent_not_required():
    # Regression test: consent_required must be False when nothing on the page
    # needs consent — report.py uses this to avoid a misleading "nicht erkannt"
    # for sites that simply don't need a cookie banner.
    html = "<html><body>Nothing tracked here.</body></html>"
    soup = BeautifulSoup(html, "lxml")
    with patch("httpx.Client", return_value=_client_mock(404)):
        result = legal.run("https://x.de", html, soup, {})
    assert result["consent_required"] is False


def test_tracking_without_banner_means_consent_required():
    html = "<html><body><script>gtag('config', 'x')</script></body></html>"
    soup = BeautifulSoup(html, "lxml")
    with patch("httpx.Client", return_value=_client_mock(404)):
        result = legal.run("https://x.de", html, soup, {})
    assert result["consent_required"] is True


def test_detects_real_cookie_banner_and_iubenda():
    # Regression test: COOKIE_SOLUTIONS was missing several widely-used CMPs
    # (Real Cookie Banner, Iubenda, consentmanager.net, CookieYes, Cookiefirst,
    # Klaro, Termly, Osano) — spot-check two of them. Real Cookie Banner's own
    # markup contains the substring "cookie-banner", which the generic pattern
    # already earlier in the list matches first — still correctly flags a banner
    # as present, just doesn't necessarily win with its own specific label.
    html = '<html><body><div id="real-cookie-banner"></div></body></html>'
    soup = BeautifulSoup(html, "lxml")
    with patch("httpx.Client", return_value=_client_mock(404)):
        result = legal.run("https://x.de", html, soup, {})
    assert result["cookie_banner_detected"] is True

    html2 = '<html><head><script src="https://cdn.iubenda.com/cs.js"></script></head></html>'
    soup2 = BeautifulSoup(html2, "lxml")
    with patch("httpx.Client", return_value=_client_mock(404)):
        result2 = legal.run("https://x.de", html2, soup2, {})
    assert result2["cookie_banner_detected"] is True
    assert result2["cookie_solution"] == "iubenda"


if __name__ == "__main__":
    test_missing_impressum_is_hoch()
    test_tracking_without_banner_is_hoch()
    test_tracking_with_banner_is_mittel()
    test_error_path_returns_error_key()
    test_no_tracking_means_consent_not_required()
    test_tracking_without_banner_means_consent_required()
    test_detects_real_cookie_banner_and_iubenda()
    print("test_legal: all tests passed")
