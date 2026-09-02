"""Assert-based smoke test for auditor.checks.security. Run: uv run python test_security.py"""
from unittest.mock import patch, MagicMock
from bs4 import BeautifulSoup
from auditor.checks import security


def _mock_redirect_response():
    r = MagicMock()
    r.url = "https://tobeworks.de/"
    r.history = [MagicMock(url="http://tobeworks.de/")]
    return r


def test_missing_hsts_is_hoch():
    with patch("httpx.get", return_value=_mock_redirect_response()), \
         patch("auditor.checks.security._check_certificate", return_value=(True, 200, "2027-01-01")):
        result = security.run("https://tobeworks.de", "<html></html>", BeautifulSoup("", "lxml"), {})
    f = next(f for f in result["findings"] if f["id"] == "SEC-02")
    assert f["severity"] == "HOCH"
    assert f["solution"]


def test_full_header_set_gives_positiv_findings():
    headers = {
        "strict-transport-security": "max-age=31536000; includeSubDomains; preload",
        "content-security-policy": "default-src 'self'",
        "x-frame-options": "SAMEORIGIN",
        "x-content-type-options": "nosniff",
        "referrer-policy": "strict-origin-when-cross-origin",
        "permissions-policy": "camera=()",
    }
    with patch("httpx.get", return_value=_mock_redirect_response()), \
         patch("auditor.checks.security._check_certificate", return_value=(True, 200, "2027-01-01")):
        result = security.run("https://tobeworks.de", "<html></html>", BeautifulSoup("", "lxml"), headers)
    ids = {f["id"]: f["severity"] for f in result["findings"]}
    assert ids["SEC-02"] == "POSITIV"
    assert ids["SEC-03"] == "POSITIV"
    assert ids["SEC-04"] == "POSITIV"
    assert "issues" not in result


def test_expired_cert_is_kritisch():
    with patch("httpx.get", return_value=_mock_redirect_response()), \
         patch("auditor.checks.security._check_certificate", return_value=(False, -5, "2020-01-01")):
        result = security.run("https://tobeworks.de", "<html></html>", BeautifulSoup("", "lxml"), {})
    f = next(f for f in result["findings"] if f["id"] == "SEC-09")
    assert f["severity"] == "KRITISCH"


def test_error_path_returns_error_key():
    # A plain httpx.get failure is already caught internally by the module (matches
    # old behavior — https_redirect just stays False), so force a real top-level
    # failure via a broken soup instead.
    class BoomSoup:
        def find_all(self, *a, **k):
            raise RuntimeError("boom")
    result = security.run("https://tobeworks.de", "<html></html>", BoomSoup(), {})
    assert "error" in result


if __name__ == "__main__":
    test_missing_hsts_is_hoch()
    test_full_header_set_gives_positiv_findings()
    test_expired_cert_is_kritisch()
    test_error_path_returns_error_key()
    print("test_security: all tests passed")
