"""Assert-based smoke test for auditor.checks.wordpress. Run: uv run python test/test_wordpress.py"""
from bs4 import BeautifulSoup
from auditor.checks import wordpress


def test_detects_wordpress_and_returns_empty_findings():
    html = '<html><head><meta name="generator" content="WordPress 6.5.2"></head><body></body></html>'
    soup = BeautifulSoup(html, "lxml")
    result = wordpress.run("https://x.de", html, soup, {})
    assert result["is_wordpress"] is True
    assert result["version"] == "6.5.2"
    assert result["findings"] == []


def test_error_path_returns_error_key():
    class BoomSoup:
        def find(self, *a, **k):
            raise RuntimeError("boom")
    result = wordpress.run("https://x.de", "<html></html>", BoomSoup(), {})
    assert "error" in result


if __name__ == "__main__":
    test_detects_wordpress_and_returns_empty_findings()
    test_error_path_returns_error_key()
    print("test_wordpress: all tests passed")
