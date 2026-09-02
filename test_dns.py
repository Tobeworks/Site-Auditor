"""Assert-based smoke test for auditor.checks.dns. Run: uv run python test_dns.py"""
from unittest.mock import patch
from auditor.checks import dns as dns_check


def test_missing_spf_is_mittel():
    with patch.object(dns_check, "_query", return_value=[]), \
         patch("httpx.head", side_effect=Exception("no network in tests")):
        result = dns_check.run("https://x.de", "", None, {})
    f = next(f for f in result["findings"] if f["id"] == "DNS-01")
    assert f["severity"] == "MITTEL"


def test_dmarc_policy_none_is_mittel():
    class Rec:
        def __init__(self, text):
            self._t = text
        def to_text(self):
            return self._t

    def fake_query(domain, rtype):
        if domain.startswith("_dmarc.") and rtype == "TXT":
            return [Rec('"v=DMARC1; p=none;"')]
        return []

    with patch.object(dns_check, "_query", side_effect=fake_query), \
         patch("httpx.head", side_effect=Exception("no network in tests")):
        result = dns_check.run("https://x.de", "", None, {})
    f = next(f for f in result["findings"] if f["id"] == "DNS-02")
    assert f["severity"] == "MITTEL"
    assert "none" in f["finding"]


def test_error_path_returns_error_key():
    with patch.object(dns_check, "_query", side_effect=RuntimeError("boom")):
        result = dns_check.run("https://x.de", "", None, {})
    assert "error" in result


if __name__ == "__main__":
    test_missing_spf_is_mittel()
    test_dmarc_policy_none_is_mittel()
    test_error_path_returns_error_key()
    print("test_dns: all tests passed")
