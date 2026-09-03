"""Assert-based smoke test for auditor.checks.seo. Run: uv run python test/test_seo.py"""
from bs4 import BeautifulSoup
from auditor.checks import seo

GOOD_HTML = """
<html lang="de"><head>
<title>Website Audits für WordPress-Betreiber – tobeworks</title>
<meta name="description" content="Wir analysieren WordPress-Seiten auf Sicherheit, SEO und Performance und liefern einen umsetzbaren Maßnahmenplan in wenigen Minuten.">
<link rel="canonical" href="https://tobeworks.de/">
<meta property="og:image" content="https://tobeworks.de/og.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:type" content="website">
<meta name="twitter:card" content="summary_large_image">
<link rel="icon" href="/favicon.ico">
</head><body><h1>Website Audits</h1></body></html>
"""


def test_missing_title_is_hoch_with_solution():
    soup = BeautifulSoup("<html><body><h1>x</h1></body></html>", "lxml")
    result = seo.run("https://tobeworks.de", "<html></html>", soup, {})
    f = next(f for f in result["findings"] if f["id"] == "SEO-01")
    assert f["severity"] == "HOCH"
    assert f["solution"]


def test_clean_page_has_positiv_findings_and_no_missing_title():
    soup = BeautifulSoup(GOOD_HTML, "lxml")
    result = seo.run("https://tobeworks.de", GOOD_HTML, soup, {})
    ids = {f["id"]: f for f in result["findings"]}
    assert "SEO-01" not in ids or ids["SEO-01"]["severity"] == "POSITIV"
    assert ids["SEO-04"]["severity"] == "POSITIV"
    assert any(f["severity"] == "POSITIV" for f in result["findings"])
    assert "issues" not in result


def test_error_path_returns_error_key():
    class BoomSoup:
        def find(self, *a, **k):
            raise RuntimeError("boom")
    result = seo.run("https://tobeworks.de", "<html></html>", BoomSoup(), {})
    assert "error" in result


if __name__ == "__main__":
    test_missing_title_is_hoch_with_solution()
    test_clean_page_has_positiv_findings_and_no_missing_title()
    test_error_path_returns_error_key()
    print("test_seo: all tests passed")
