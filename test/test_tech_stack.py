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


def test_detects_astro_via_generator_meta():
    html = '<html><head><meta name="generator" content="Astro v4.5.0"></head></html>'
    soup = BeautifulSoup(html, "lxml")
    result = tech_stack.run("https://x.de", html, soup, {})
    assert result["framework"] == "Astro"


def test_detects_astro_via_island_element():
    # Real Astro output has no generator meta tag in practice — the actual signal
    # is the <astro-island> custom ELEMENT (not a CSS class) plus /_astro/ assets.
    # Regression test: an earlier version of this check searched for "astro-island"
    # as a class name, which never matches, silently missing every real Astro site.
    html = '<html><body><astro-island component-url="/_astro/Foo.js"></astro-island></body></html>'
    soup = BeautifulSoup(html, "lxml")
    result = tech_stack.run("https://x.de", html, soup, {})
    assert result["framework"] == "Astro"


def test_detects_nextjs_via_asset_path():
    html = '<html><body><script src="/_next/static/chunks/main.js"></script></body></html>'
    soup = BeautifulSoup(html, "lxml")
    result = tech_stack.run("https://x.de", html, soup, {})
    assert result["framework"] == "Next.js"


def test_detects_nuxt_via_root_id():
    html = '<html><body><div id="__nuxt"><div id="__layout"></div></div></body></html>'
    soup = BeautifulSoup(html, "lxml")
    result = tech_stack.run("https://x.de", html, soup, {})
    assert result["framework"] == "Nuxt"


def test_detects_wix_via_generator_meta():
    html = '<html><head><meta name="generator" content="Wix.com Website Builder"></head></html>'
    soup = BeautifulSoup(html, "lxml")
    result = tech_stack.run("https://x.de", html, soup, {})
    assert result["framework"] == "Wix"


def test_no_framework_detected_is_none():
    html = "<html><body>Plain HTML, no framework markers.</body></html>"
    soup = BeautifulSoup(html, "lxml")
    result = tech_stack.run("https://x.de", html, soup, {})
    assert result["framework"] is None


if __name__ == "__main__":
    test_returns_findings_key_as_empty_list()
    test_error_path_returns_error_key()
    test_detects_bricks_builder()
    test_detects_astro_via_generator_meta()
    test_detects_astro_via_island_element()
    test_detects_nextjs_via_asset_path()
    test_detects_nuxt_via_root_id()
    test_detects_wix_via_generator_meta()
    test_no_framework_detected_is_none()
    print("test_tech_stack: all tests passed")
