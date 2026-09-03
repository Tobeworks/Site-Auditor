"""Assert-based smoke test for auditor.checks.wordpress_deep. Run: uv run python test/test_wordpress_deep.py"""
from unittest.mock import patch, MagicMock
from bs4 import BeautifulSoup
from auditor.checks import wordpress_deep


def _client_mock(head_status=404, get_status=404, get_json=None):
    client = MagicMock()
    client.__enter__.return_value = client
    client.head.return_value = MagicMock(status_code=head_status)
    client.get.return_value = MagicMock(status_code=get_status, json=MagicMock(return_value=get_json or []))
    return client


def test_debug_log_exposed_is_kritisch():
    with patch("httpx.Client", return_value=_client_mock(head_status=200)), \
         patch("httpx.get", return_value=MagicMock(json=MagicMock(return_value={"offers": [{"version": "6.5.2"}]}))):
        result = wordpress_deep.run("https://x.de", "<html></html>", BeautifulSoup("", "lxml"), {})
    f = next(f for f in result["findings"] if f["id"] == "WPD-05")
    assert f["severity"] == "KRITISCH"


def test_outdated_wp_version_is_hoch():
    html = '<html><head><meta name="generator" content="WordPress 6.0.0"></head></html>'
    soup = BeautifulSoup(html, "lxml")
    with patch("httpx.Client", return_value=_client_mock()), \
         patch("httpx.get", return_value=MagicMock(json=MagicMock(return_value={"offers": [{"version": "6.5.2"}]}))):
        result = wordpress_deep.run("https://x.de", html, soup, {})
    assert result["wp_version_detected"] == "6.0.0"
    assert result["wp_version_current"] is False
    f = next(f for f in result["findings"] if f["id"] == "WPD-09")
    assert f["severity"] == "HOCH"


def test_current_wp_version_is_positiv():
    html = '<html><head><meta name="generator" content="WordPress 6.5.2"></head></html>'
    soup = BeautifulSoup(html, "lxml")
    with patch("httpx.Client", return_value=_client_mock()), \
         patch("httpx.get", return_value=MagicMock(json=MagicMock(return_value={"offers": [{"version": "6.5.2"}]}))):
        result = wordpress_deep.run("https://x.de", html, soup, {})
    assert result["wp_version_current"] is True
    f = next(f for f in result["findings"] if f["id"] == "WPD-09")
    assert f["severity"] == "POSITIV"


def test_error_path_returns_error_key():
    with patch("httpx.Client", side_effect=RuntimeError("boom")):
        result = wordpress_deep.run("https://x.de", "<html></html>", BeautifulSoup("", "lxml"), {})
    assert "error" in result


if __name__ == "__main__":
    test_debug_log_exposed_is_kritisch()
    test_outdated_wp_version_is_hoch()
    test_current_wp_version_is_positiv()
    test_error_path_returns_error_key()
    print("test_wordpress_deep: all tests passed")
