"""Assert-based smoke test for auditor.checks.broken_links. Run: uv run python test/test_broken_links.py"""
from unittest.mock import patch
from bs4 import BeautifulSoup
from auditor.checks import broken_links


def test_broken_link_is_mittel():
    html = '<a href="/kaputt">Link</a>'
    soup = BeautifulSoup(html, "lxml")
    with patch.object(broken_links, "_check_links", return_value=([{"url": "https://x.de/kaputt", "status": 404}], [], [])):
        result = broken_links.run("https://x.de", html, soup, {})
    f = next(f for f in result["findings"] if f["id"] == "LNK-01")
    assert f["severity"] == "MITTEL"


def test_no_broken_links_is_positiv():
    html = '<a href="/ok">Link</a>'
    soup = BeautifulSoup(html, "lxml")
    with patch.object(broken_links, "_check_links", return_value=([], [], [])):
        result = broken_links.run("https://x.de", html, soup, {})
    f = next(f for f in result["findings"] if f["id"] == "LNK-01")
    assert f["severity"] == "POSITIV"
    assert "issues" not in result


def test_no_internal_links_skips_lnk01():
    soup = BeautifulSoup("<html></html>", "lxml")
    result = broken_links.run("https://x.de", "<html></html>", soup, {})
    assert not any(f["id"] == "LNK-01" for f in result["findings"])


if __name__ == "__main__":
    test_broken_link_is_mittel()
    test_no_broken_links_is_positiv()
    test_no_internal_links_skips_lnk01()
    print("test_broken_links: all tests passed")
