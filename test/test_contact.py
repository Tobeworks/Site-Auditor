"""Assert-based smoke test for auditor.checks.contact. Run: uv run python test/test_contact.py"""
from bs4 import BeautifulSoup
from auditor.checks import contact

FILLER = "Wir bauen Websites für Unternehmen aus der Region und beraten persönlich. " * 4


def _run(body: str):
    html = f"<html><body>{body}</body></html>"
    return contact.run("https://x.de/", html, BeautifulSoup(html, "lxml"), {})


def _ids(result):
    return {f["id"] for f in result["findings"]}


def test_tel_link_is_clickable():
    r = _run(f'<p>{FILLER}</p><a href="tel:+496131123456">06131 123456</a>')
    assert r["has_tel"] is True and r["tel_clickable"] is True
    assert "KON-01" not in _ids(r)


def test_plain_phone_number_is_found_but_not_clickable():
    r = _run(f"<p>{FILLER}</p><p>Telefon: 06131 123456</p>")
    assert r["has_tel"] is True and r["tel_clickable"] is False
    f = next(f for f in r["findings"] if f["id"] == "KON-01")
    assert f["severity"] == "MITTEL"


def test_phone_pattern_does_not_match_dates_or_years():
    r = _run(f"<p>{FILLER}</p><p>Stand 01.01.2024, seit 1999, Version 12.3.4567</p>")
    assert r["has_tel"] is False


def test_mailto_and_form_detected():
    r = _run(f'<p>{FILLER}</p><a href="mailto:hallo@x.de">Mail</a><form><textarea name="m"></textarea></form>')
    assert r["has_mail"] is True and r["has_form"] is True


def test_search_form_is_not_a_contact_form():
    r = _run(f'<p>{FILLER}</p><form role="search"><input type="search" name="s"></form>')
    assert r["has_form"] is False


def test_contact_link_detected():
    r = _run(f'<p>{FILLER}</p><a href="/kontakt/">Kontakt</a>')
    assert r["has_contact_link"] is True
    assert "KON-02" not in _ids(r)


def test_nothing_found_is_mittel_not_hoch():
    r = _run(f"<p>{FILLER}</p>")
    f = next(f for f in r["findings"] if f["id"] == "KON-02")
    assert f["severity"] == "MITTEL"


def test_form_provider_script_counts_as_form():
    r = _run(f'<p>{FILLER}</p><script src="https://embed.typeform.com/next/embed.js"></script>')
    assert r["has_form"] is True
    assert "KON-02" not in _ids(r)


def test_almost_empty_page_gets_no_negative_finding():
    # Vermutlich per JavaScript gerendert, dann wäre "kein Kontaktweg" eine Falschmeldung.
    r = _run('<div id="app"></div><script src="/app.js"></script>')
    assert "KON-02" not in _ids(r)


def test_error_path_returns_error_key():
    class BoomSoup:
        def find_all(self, *a, **k):
            raise RuntimeError("boom")
    result = contact.run("https://x.de/", "<html></html>", BoomSoup(), {})
    assert "error" in result


if __name__ == "__main__":
    test_tel_link_is_clickable()
    test_plain_phone_number_is_found_but_not_clickable()
    test_phone_pattern_does_not_match_dates_or_years()
    test_mailto_and_form_detected()
    test_search_form_is_not_a_contact_form()
    test_contact_link_detected()
    test_nothing_found_is_mittel_not_hoch()
    test_form_provider_script_counts_as_form()
    test_almost_empty_page_gets_no_negative_finding()
    test_error_path_returns_error_key()
    print("test_contact: all tests passed")
