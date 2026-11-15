"""Assert-based smoke test for auditor.checks.accessibility_static. Run: uv run python test/test_accessibility_static.py"""
from bs4 import BeautifulSoup
from auditor.checks import accessibility_static


def _run(html: str):
    return accessibility_static.run("https://x.de/", html, BeautifulSoup(html, "lxml"), {})


def _ids(result):
    return {f["id"] for f in result["findings"]}


CLEAN = '<html lang="de"><body><h1>Hallo</h1><img src="a.png" alt="Ein Bild"></body></html>'


def test_missing_lang_is_mittel():
    r = _run("<html><body><p>x</p></body></html>")
    assert r["lang"] is None
    assert next(f for f in r["findings"] if f["id"] == "BAR-01")["severity"] == "MITTEL"


def test_lang_present_has_no_finding():
    r = _run(CLEAN)
    assert r["lang"] == "de"
    assert "BAR-01" not in _ids(r)


def test_images_without_alt_counted_and_empty_alt_is_decorative():
    r = _run('<html lang="de"><body><img src="a.png"><img src="b.png" alt=""><img src="c.png" alt="Logo"></body></html>')
    assert r["images_total"] == 3
    assert r["images_without_alt"] == 1
    f = next(f for f in r["findings"] if f["id"] == "BAR-02")
    assert "1" in f["finding"]


def test_unlabeled_form_fields():
    html = ('<html lang="de"><body><form>'
            '<input type="text" name="a">'                                  # ohne Beschriftung
            '<input type="text" id="b"><label for="b">Name</label>'          # beschriftet
            '<input type="text" aria-label="Suche">'                         # beschriftet
            '<label>Mail <input type="email"></label>'                       # umschlossen
            '<input type="hidden" name="h"><input type="submit" value="Senden">'
            '</form></body></html>')
    r = _run(html)
    assert r["unlabeled_fields"] == 1
    assert "BAR-03" in _ids(r)


def test_accessibility_statement_link_detected():
    r = _run('<html lang="de"><body><a href="/barrierefreiheit/">Barrierefreiheitserklärung</a></body></html>')
    assert r["accessibility_statement"] is True
    assert next(f for f in r["findings"] if f["id"] == "BAR-04")["severity"] == "POSITIV"


def test_missing_statement_gives_no_negative_finding():
    r = _run(CLEAN)
    assert r["accessibility_statement"] is False
    assert "BAR-04" not in _ids(r)


def test_clean_page_has_no_negative_findings():
    r = _run(CLEAN)
    assert [f for f in r["findings"] if f["severity"] != "POSITIV"] == []


def test_error_path_returns_error_key():
    class BoomSoup:
        def find(self, *a, **k):
            raise RuntimeError("boom")
        find_all = find
    result = accessibility_static.run("https://x.de/", "<html></html>", BoomSoup(), {})
    assert "error" in result


if __name__ == "__main__":
    test_missing_lang_is_mittel()
    test_lang_present_has_no_finding()
    test_images_without_alt_counted_and_empty_alt_is_decorative()
    test_unlabeled_form_fields()
    test_accessibility_statement_link_detected()
    test_missing_statement_gives_no_negative_finding()
    test_clean_page_has_no_negative_findings()
    test_error_path_returns_error_key()
    print("test_accessibility_static: all tests passed")
