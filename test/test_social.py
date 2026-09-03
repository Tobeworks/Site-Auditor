"""Assert-based smoke test for auditor.checks.social. Run: uv run python test/test_social.py"""
from unittest.mock import patch, MagicMock
from bs4 import BeautifulSoup
from auditor.checks import social


def _client_mock(robots_txt: str, head_status=200):
    client = MagicMock()
    client.__enter__.return_value = client

    def head(url, **kw):
        return MagicMock(status_code=head_status)

    def get(url, **kw):
        if url.endswith("/robots.txt"):
            return MagicMock(status_code=200, text=robots_txt)
        return MagicMock(status_code=404, text="")

    client.head.side_effect = head
    client.get.side_effect = get
    return client


def test_multiple_star_groups_is_hoch():
    robots = "User-agent: *\nDisallow: /admin\n\nUser-agent: *\nDisallow: /private\n"
    with patch("httpx.Client", return_value=_client_mock(robots)):
        result = social.run("https://x.de/", "<html></html>", BeautifulSoup("", "lxml"), {})
    f = next(f for f in result["findings"] if f["id"] == "SOC-06" and f["severity"] == "HOCH")
    assert "*-Blöcke" in f["finding"] or "*-Bl" in f["finding"]


def test_weaker_bot_group_is_mittel():
    # Both Googlebot (Disallow: /) and Bingbot (Disallow: <empty>) end up weaker than
    # the *-group's "Disallow: /admin" — filter for the Bingbot one specifically,
    # next() on severity alone would nondeterministically grab either.
    robots = "User-agent: *\nDisallow: /admin\n\nUser-agent: Googlebot\nDisallow: /\n\nUser-agent: Bingbot\nDisallow:\n"
    with patch("httpx.Client", return_value=_client_mock(robots)):
        result = social.run("https://x.de/", "<html></html>", BeautifulSoup("", "lxml"), {})
    f = next(f for f in result["findings"]
             if f["id"] == "SOC-06" and f["severity"] == "MITTEL" and "Bingbot" in f["finding"])
    assert "/admin" in f["finding"]


def test_invalid_hreflang_is_mittel():
    html = (
        '<link rel="alternate" hreflang="es-xx" href="https://x.de/es/">'
        '<link rel="alternate" hreflang="de" href="https://x.de/de/">'
    )
    soup = BeautifulSoup(f"<html><head>{html}</head></html>", "lxml")
    with patch("httpx.Client", return_value=_client_mock("User-agent: *\nDisallow:\n")):
        result = social.run("https://x.de/", html, soup, {})
    f = next(f for f in result["findings"] if f["id"] == "SOC-07")
    assert f["severity"] == "MITTEL"
    assert "es-xx" in f["finding"]


def test_missing_x_default_is_mittel():
    html = '<link rel="alternate" hreflang="de" href="https://x.de/de/">'
    soup = BeautifulSoup(f"<html><head>{html}</head></html>", "lxml")
    with patch("httpx.Client", return_value=_client_mock("User-agent: *\nDisallow:\n")):
        result = social.run("https://x.de/", html, soup, {})
    f = next(f for f in result["findings"] if f["id"] == "SOC-08")
    assert f["severity"] == "MITTEL"


def test_error_path_returns_error_key():
    class BoomSoup:
        def find(self, *a, **k):
            raise RuntimeError("boom")
        def find_all(self, *a, **k):
            raise RuntimeError("boom")
    result = social.run("https://x.de/", "<html></html>", BoomSoup(), {})
    assert "error" in result


def test_sitemap_declared_only_in_robots_txt_is_found():
    # None of the guessed filenames exist (all 404) — only robots.txt's
    # Sitemap: directive, with a non-standard filename, points to a real one.
    # Regression test for the bug where sitemap discovery only ever guessed
    # fixed filenames and never read robots.txt's authoritative Sitemap: line.
    robots = "User-agent: *\nDisallow:\nSitemap: https://x.de/sitemap-custom-name.xml\n"
    client = MagicMock()
    client.__enter__.return_value = client

    def head(url, **kw):
        status = 200 if url == "https://x.de/sitemap-custom-name.xml" else 404
        return MagicMock(status_code=status)

    def get(url, **kw):
        if url.endswith("/robots.txt"):
            return MagicMock(status_code=200, text=robots)
        return MagicMock(status_code=404, text="")

    client.head.side_effect = head
    client.get.side_effect = get

    with patch("httpx.Client", return_value=client):
        result = social.run("https://x.de/", "<html></html>", BeautifulSoup("", "lxml"), {})
    assert result["sitemap_urls"] == ["https://x.de/sitemap-custom-name.xml"]
    f = next(f for f in result["findings"] if f["id"] == "SOC-03")
    assert f["severity"] == "POSITIV"


if __name__ == "__main__":
    test_multiple_star_groups_is_hoch()
    test_weaker_bot_group_is_mittel()
    test_invalid_hreflang_is_mittel()
    test_missing_x_default_is_mittel()
    test_error_path_returns_error_key()
    test_sitemap_declared_only_in_robots_txt_is_found()
    print("test_social: all tests passed")
