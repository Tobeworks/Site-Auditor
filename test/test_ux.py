"""ux.run mit vorgegebenen Browserdaten (keine Verbindung nötig)."""
from bs4 import BeautifulSoup

from auditor.checks import ux

OK_META = '<meta name="viewport" content="width=device-width, initial-scale=1">'


def _run(head="", mobile=None, status="ok"):
    html = f"<html><head>{head}</head><body></body></html>"
    fv = {"status": status, "mobile": mobile} if mobile is not None else None
    return ux.run("https://x.de", html, BeautifulSoup(html, "lxml"), {}, first_view=fv)


def _sev(result, fid):
    return next(f["severity"] for f in result["findings"] if f["id"] == fid)


GOOD = {"targets": 10, "small": 0, "cta": True, "overflowX": False, "scrollWidth": 390, "width": 390}


def test_missing_viewport_meta_is_hoch_and_present_is_positiv():
    assert _sev(_run(), "UXF-01") == "HOCH"
    assert _sev(_run(OK_META), "UXF-01") == "POSITIV"


def test_without_browser_data_only_the_viewport_check_runs():
    result = _run(OK_META)
    assert [f["id"] for f in result["findings"]] == ["UXF-01"] and result["browser"] is False


def test_horizontal_scroll_is_hoch():
    assert _sev(_run(OK_META, {**GOOD, "overflowX": True, "scrollWidth": 700}), "UXF-02") == "HOCH"


def test_no_action_in_first_screen_is_mittel():
    assert _sev(_run(OK_META, {**GOOD, "cta": False}), "UXF-03") == "MITTEL"
    assert _sev(_run(OK_META, GOOD), "UXF-03") == "POSITIV"


def test_overlay_page_gets_no_cta_verdict():
    result = _run(OK_META, {**GOOD, "cta": False}, status="empty")
    assert "UXF-03" not in [f["id"] for f in result["findings"]]


def test_small_targets_need_count_and_share():
    assert "UXF-04" in [f["id"] for f in _run(OK_META, {**GOOD, "targets": 10, "small": 4})["findings"]]
    assert "UXF-04" not in [f["id"] for f in _run(OK_META, {**GOOD, "targets": 40, "small": 4})["findings"]]  # Anteil zu klein
    assert "UXF-04" not in [f["id"] for f in _run(OK_META, {**GOOD, "targets": 3, "small": 2})["findings"]]  # zu wenige
