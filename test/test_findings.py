"""Assert-based smoke test for auditor.findings. Run: uv run python test_findings.py"""
from auditor.findings import finding, CATEGORY_MAP


def test_valid_finding_has_all_fields():
    f = finding("SEO-01", "HOCH", "Kein <title>-Tag vorhanden", "Google generiert den Snippet selbst.", solution="Title-Tag ergänzen.")
    assert f == {
        "id": "SEO-01", "severity": "HOCH",
        "finding": "Kein <title>-Tag vorhanden",
        "impact": "Google generiert den Snippet selbst.",
        "solution": "Title-Tag ergänzen.",
        "effort_days": None, "timeframe": None,
    }


def test_positiv_forbids_solution():
    try:
        finding("SEO-01", "POSITIV", "Title optimal", "—", solution="nicht erlaubt")
        assert False, "sollte ValueError werfen"
    except ValueError:
        pass


def test_non_positiv_requires_solution():
    try:
        finding("SEO-01", "HOCH", "Kein <title>-Tag", "—")
        assert False, "sollte ValueError werfen"
    except ValueError:
        pass


def test_positiv_finding_has_none_solution():
    f = finding("SEO-01", "POSITIV", "Title optimal", "—")
    assert f["solution"] is None


def test_category_map_covers_all_prefixes():
    expected_prefixes = {"SEO", "SDA", "PRF", "SEC", "HST", "SOC", "LNK", "MKP", "TCH", "WPR", "WPD", "DNS", "CNT", "LGL", "A11"}
    assert expected_prefixes.issubset(CATEGORY_MAP.keys())


if __name__ == "__main__":
    test_valid_finding_has_all_fields()
    test_positiv_forbids_solution()
    test_non_positiv_requires_solution()
    test_positiv_finding_has_none_solution()
    test_category_map_covers_all_prefixes()
    print("test_findings: all tests passed")
