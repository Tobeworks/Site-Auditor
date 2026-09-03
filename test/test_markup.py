"""Assert-based smoke test for auditor.checks.markup. Run: uv run python test_markup.py"""
from unittest.mock import patch, MagicMock
from bs4 import BeautifulSoup
from auditor.checks import markup


def _mock_response(json_body, status_code=200):
    r = MagicMock()
    r.status_code = status_code
    r.raise_for_status = MagicMock() if status_code < 400 else MagicMock(side_effect=Exception("HTTP error"))
    r.json.return_value = json_body
    return r


def test_errors_populate_findings():
    body = {"messages": [
        {"type": "error", "message": "Element head is missing a required instance of child element title.", "lastLine": 3},
        {"type": "info", "subType": "warning", "message": "minor nit"},
    ]}
    with patch("httpx.post", return_value=_mock_response(body)):
        result = markup.run("https://tobeworks.de", "<html></html>", BeautifulSoup("", "lxml"), {})
    assert result["error_count"] == 1
    assert result["warning_count"] == 1
    findings = [f for f in result["findings"] if f["id"] == "MKP-01"]
    assert len(findings) == 1
    assert findings[0]["severity"] == "MITTEL"
    assert "title" in findings[0]["finding"]


def test_clean_page_has_positiv_finding():
    with patch("httpx.post", return_value=_mock_response({"messages": []})):
        result = markup.run("https://tobeworks.de", "<html></html>", BeautifulSoup("", "lxml"), {})
    assert result["error_count"] == 0
    f = next(f for f in result["findings"] if f["id"] == "MKP-01")
    assert f["severity"] == "POSITIV"


def test_network_failure_returns_error_key():
    with patch("httpx.post", side_effect=Exception("timeout")):
        result = markup.run("https://tobeworks.de", "<html></html>", BeautifulSoup("", "lxml"), {})
    assert "error" in result


if __name__ == "__main__":
    test_errors_populate_findings()
    test_clean_page_has_positiv_finding()
    test_network_failure_returns_error_key()
    print("test_markup: all tests passed")
