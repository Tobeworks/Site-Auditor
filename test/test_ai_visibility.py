"""Assert-based smoke test for auditor.checks.ai_visibility. Run: uv run python test/test_ai_visibility.py"""
from unittest.mock import patch, MagicMock
from bs4 import BeautifulSoup
from auditor.checks import ai_visibility


def _client_mock(robots_txt=None, llms_txt=None):
    client = MagicMock()
    client.__enter__.return_value = client

    def get(url, **kw):
        if url.endswith("/robots.txt") and robots_txt is not None:
            return MagicMock(status_code=200, text=robots_txt)
        if url.endswith("/llms.txt") and llms_txt is not None:
            return MagicMock(status_code=200, text=llms_txt)
        return MagicMock(status_code=404, text="")

    client.get.side_effect = get
    return client


def _run(robots_txt=None, llms_txt=None):
    with patch("httpx.Client", return_value=_client_mock(robots_txt, llms_txt)):
        return ai_visibility.run("https://x.de/", "<html></html>", BeautifulSoup("", "lxml"), {})


def test_blocked_search_crawler_is_reported():
    result = _run("User-agent: OAI-SearchBot\nDisallow: /\n")
    assert result["blocked_crawlers"] == ["OAI-SearchBot"]
    f = next(f for f in result["findings"] if f["id"] == "KIS-01")
    assert f["severity"] == "MITTEL"
    assert "OAI-SearchBot" in f["finding"] and "KI-Suche" in f["impact"]


def test_training_only_block_is_listed_but_gives_no_finding():
    # Das Training zu sperren ist eine verbreitete, bewusste Entscheidung und sagt nichts über Antworten in KI-Suchen.
    result = _run("User-agent: GPTBot\nUser-agent: CCBot\nUser-agent: Google-Extended\nDisallow: /\n\nUser-agent: OAI-SearchBot\nAllow: /\n")
    assert result["blocked_crawlers"] == ["GPTBot", "Google-Extended", "CCBot"] or set(result["blocked_crawlers"]) == {"GPTBot", "CCBot", "Google-Extended"}
    assert not any(f["id"] == "KIS-01" for f in result["findings"])


def test_wildcard_disallow_alone_is_not_an_ai_finding():
    # Die Gesamtsperre meldet SOC-01, hier wird nur gezielt gegen KI-Crawler gemeldet.
    result = _run("User-agent: *\nDisallow: /\n")
    assert result["blocked_crawlers"] == []
    assert not any(f["id"] == "KIS-01" for f in result["findings"])


def test_allow_after_disallow_is_not_blocked():
    result = _run("User-agent: ClaudeBot\nDisallow: /\nAllow: /\n")
    assert result["blocked_crawlers"] == []


def test_partial_disallow_is_not_blocked():
    result = _run("User-agent: GPTBot\nDisallow: /intern/\n")
    assert result["blocked_crawlers"] == []


def test_several_agents_in_one_group_are_all_blocked():
    result = _run("User-agent: GPTBot\nUser-agent: PerplexityBot\nDisallow: /\n")
    assert set(result["blocked_crawlers"]) == {"GPTBot", "PerplexityBot"}
    assert "PerplexityBot" in next(f for f in result["findings"] if f["id"] == "KIS-01")["finding"]


def test_no_robots_txt_no_finding():
    result = _run(None)
    assert result["blocked_crawlers"] == []
    assert result["findings"] == []


def test_llms_txt_present_is_positive_only():
    result = _run(None, "# Seite\n> Kurzbeschreibung\n")
    assert result["llms_txt"] is True
    f = next(f for f in result["findings"] if f["id"] == "KIS-02")
    assert f["severity"] == "POSITIV"


def test_missing_llms_txt_gives_no_finding():
    result = _run(None, None)
    assert result["llms_txt"] is False
    assert not any(f["id"] == "KIS-02" for f in result["findings"])


def test_html_soft_404_is_not_an_llms_txt():
    result = _run(None, "<!DOCTYPE html><html><body>Seite nicht gefunden</body></html>")
    assert result["llms_txt"] is False


def test_error_path_returns_error_key():
    with patch("httpx.Client", side_effect=RuntimeError("boom")):
        result = ai_visibility.run("https://x.de/", "<html></html>", BeautifulSoup("", "lxml"), {})
    assert "error" in result


if __name__ == "__main__":
    test_blocked_search_crawler_is_reported()
    test_training_only_block_is_listed_but_gives_no_finding()
    test_wildcard_disallow_alone_is_not_an_ai_finding()
    test_allow_after_disallow_is_not_blocked()
    test_partial_disallow_is_not_blocked()
    test_several_agents_in_one_group_are_all_blocked()
    test_no_robots_txt_no_finding()
    test_llms_txt_present_is_positive_only()
    test_missing_llms_txt_gives_no_finding()
    test_html_soft_404_is_not_an_llms_txt()
    test_error_path_returns_error_key()
    print("test_ai_visibility: all tests passed")
