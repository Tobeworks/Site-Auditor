"""Assert-based smoke test for auditor.checks.hosting. Run: uv run python test_hosting.py"""
from unittest.mock import patch, MagicMock
from auditor.checks import hosting


def _mock_ipapi():
    r = MagicMock()
    r.json.return_value = {"country": "Germany", "city": "Berlin", "timezone": "Europe/Berlin", "org": "Hetzner Online GmbH"}
    return r


def test_eol_php_version_is_kritisch():
    with patch("socket.gethostbyname", return_value="1.2.3.4"), \
         patch("socket.gethostbyaddr", side_effect=Exception()), \
         patch("socket.getaddrinfo", side_effect=Exception()), \
         patch("ipwhois.IPWhois", side_effect=Exception("no network in tests")), \
         patch("httpx.get", return_value=_mock_ipapi()):
        result = hosting.run("https://x.de", "", None, {"x-powered-by": "PHP/7.4.33"})
    f = next(f for f in result["findings"] if f["id"] == "HST-04")
    assert f["severity"] == "KRITISCH"


def test_current_php_version_is_positiv():
    # 8.4's EOL (2027-12-31) is safely >183 days out from any plausible test-run
    # date in this plan's timeframe — 8.3's EOL (2026-11-23) is not, don't use it here.
    with patch("socket.gethostbyname", return_value="1.2.3.4"), \
         patch("socket.gethostbyaddr", side_effect=Exception()), \
         patch("socket.getaddrinfo", side_effect=Exception()), \
         patch("ipwhois.IPWhois", side_effect=Exception("no network in tests")), \
         patch("httpx.get", return_value=_mock_ipapi()):
        result = hosting.run("https://x.de", "", None, {"x-powered-by": "PHP/8.4.1"})
    f = next(f for f in result["findings"] if f["id"] == "HST-04")
    assert f["severity"] == "POSITIV"


def test_unresolvable_domain_returns_error_key():
    with patch("socket.gethostbyname", side_effect=Exception("nope")):
        result = hosting.run("https://doesnotresolve.invalid", "", None, {})
    assert "error" in result


if __name__ == "__main__":
    test_eol_php_version_is_kritisch()
    test_current_php_version_is_positiv()
    test_unresolvable_domain_returns_error_key()
    print("test_hosting: all tests passed")
