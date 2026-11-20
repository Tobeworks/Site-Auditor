"""Tests für auditor.scoring (Teilscores, Gesamtnote, "Das zuerst", Aufwandsspannen).
Run: uv run python test/test_scoring.py"""
from unittest.mock import patch

from auditor import report, runner, scoring
from auditor.findings import finding


def _f(fid, sev, **kw):
    return finding(fid, sev, f"Befund {fid}", "Wirkung", None if sev == "POSITIV" else "Lösung", **kw)


def _results():
    return {
        "wordpress": {"is_wordpress": False, "findings": []},
        "seo": {"findings": [_f("SEO-01", "HOCH"), _f("SEO-02", "MITTEL"), _f("SEO-03", "POSITIV")]},
        "security": {"findings": [_f("SEC-01", "KRITISCH")]},
        "legal": {"findings": []},
        "performance": {"error": "boom"},
    }


def test_deductions_per_severity():
    score = scoring.build_score(_results())
    assert score["categories"]["OnPage-SEO"] == 8.0          # 10 - 1,5 - 0,5, POSITIV zieht nichts ab
    assert score["categories"]["Sicherheit & Stack"] == 7.0   # 10 - 3
    assert score["categories"]["Trust & Legal"] == 10.0
    points = {d["id"]: d["points"] for d in score["deductions"]}
    assert points == {"SEO-01": 1.5, "SEO-02": 0.5, "SEC-01": 3}


def test_category_score_never_drops_below_zero():
    results = {"security": {"findings": [_f(f"SEC-{i:02d}", "KRITISCH") for i in range(1, 6)]}}
    assert scoring.build_score(results)["categories"]["Sicherheit & Stack"] == 0.0


def test_category_without_checked_module_is_not_scored():
    categories = scoring.build_score(_results())["categories"]
    assert "Performance" not in categories      # Modul mit error
    assert "UX & Funnel" not in categories       # kein Modul gelaufen
    assert "Technik & Index" not in categories   # nur die Erkennung 'wordpress' lief, die zählt nicht


def test_overall_is_mean_of_scored_categories():
    assert scoring.build_score(_results())["overall"] == 8.3   # (8 + 7 + 10) / 3


def test_no_scored_category_gives_overall_none():
    score = scoring.build_score({"wordpress": {"findings": []}})
    assert score["categories"] == {} and score["overall"] is None and score["first"] == []


def test_first_returns_three_most_important_open_findings():
    results = {"seo": {"findings": [
        _f("SEO-01", "MITTEL"), _f("SEO-02", "HOCH"), _f("SEO-03", "KRITISCH"), _f("SEO-04", "MITTEL"), _f("SEO-05", "POSITIV"),
    ]}}
    scoring.apply_effort(results)
    first = scoring.build_score(results)["first"]
    assert [f["id"] for f in first] == ["SEO-03", "SEO-02", "SEO-01"]
    assert all(f["severity"] != "POSITIV" for f in first)
    assert first[0]["solution"] == "Lösung" and len(first[0]["effort_days"]) == 2 and first[0]["timeframe"] == "kurzfristig"


def test_apply_effort_fills_every_open_finding_and_keeps_existing_values():
    results = {"seo": {"findings": [_f("SEO-01", "HOCH"), _f("SEO-02", "MITTEL", effort_days=(2.0, 3.0), timeframe="langfristig"), _f("SEO-03", "POSITIV")]}}
    scoring.apply_effort(results)
    a, b, c = results["seo"]["findings"]
    assert a["effort_days"] == (0.25, 1.0) and a["timeframe"] == "kurzfristig"
    assert b["effort_days"] == (2.0, 3.0) and b["timeframe"] == "langfristig"
    assert c["effort_days"] is None and c["timeframe"] is None


def test_apply_effort_ignores_modules_with_error():
    results = {"seo": {"error": "boom"}, "google_result": {"status": "disabled", "findings": []}}
    scoring.apply_effort(results)   # darf nicht werfen


def test_run_audit_result_contains_score():
    html = "<html><head><title>t</title></head><body></body></html>"
    from auditor.checks import ALL_CHECKS
    with patch.object(runner, "_fetch", return_value=(html, {}, 42)):
        results = runner.run_audit("https://tobeworks.de", skip=list(ALL_CHECKS))
    assert set(results["score"]) >= {"categories", "overall", "deductions", "formula", "first"}


def test_report_discloses_formula_and_plan():
    results = _results()
    scoring.apply_effort(results)
    results["score"] = scoring.build_score(results)
    md = report.build("https://x.de", results)
    assert "Score-Berechnung" in md and "Maßnahmenplan" in md and "Schätzwerte" in md
    assert "SEC-01" in md


def test_category_for_kis_is_ki_bereitschaft():
    results = {"ai_visibility": {"findings": [_f("KIS-03", "HOCH")]}, "seo": {"findings": [_f("SEO-02", "MITTEL")]}}
    score = scoring.build_score(results)
    assert score["categories"]["KI-Bereitschaft"] == 8.5
    assert score["categories"]["OnPage-SEO"] == 9.5 and "Content & Sichtbarkeit" not in score["categories"]
    assert score["first"][0]["id"] == "KIS-03"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("test_scoring: all tests passed")


def test_skipped_module_caps_its_category_and_is_listed():
    from auditor import scoring as sc
    results = {"seo": {"findings": []}, "security": {"findings": []}}
    full = sc.build_score(results)
    assert full["categories"]["Sicherheit & Stack"] == 10.0 and full["partial"] == {}
    capped = sc.build_score(results, skipped=["hosting", "wordpress_deep", "performance"])
    assert capped["categories"]["Sicherheit & Stack"] == 9.0 and capped["categories"]["OnPage-SEO"] == 10.0
    assert capped["partial"] == {"Sicherheit & Stack": ["hosting"]}  # performance hat keine geprüfte Kategorie, wordpress_deep zählt nicht
