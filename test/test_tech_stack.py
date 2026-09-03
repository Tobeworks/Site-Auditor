"""Assert-based smoke test for auditor.checks.tech_stack. Run: uv run python test/test_tech_stack.py"""
from bs4 import BeautifulSoup
from auditor.checks import tech_stack


def test_returns_findings_key_as_empty_list():
    soup = BeautifulSoup("<html></html>", "lxml")
    result = tech_stack.run("https://x.de", "<html></html>", soup, {"x-powered-by": "PHP/8.1.10"})
    assert result["findings"] == []
    assert result["php_version"] == "8.1.10"
    assert "issues" not in result


def test_error_path_returns_error_key():
    class BoomSoup:
        def find_all(self, *a, **k):
            raise RuntimeError("boom")
    result = tech_stack.run("https://x.de", "<html></html>", BoomSoup(), {})
    assert "error" in result


def test_detects_bricks_builder():
    html = '<html><body><div class="brxe-container"></div></body></html>'
    soup = BeautifulSoup(html, "lxml")
    result = tech_stack.run("https://x.de", html, soup, {})
    assert result["page_builder"] == "Bricks Builder"


if __name__ == "__main__":
    test_returns_findings_key_as_empty_list()
    test_error_path_returns_error_key()
    test_detects_bricks_builder()
    print("test_tech_stack: all tests passed")
