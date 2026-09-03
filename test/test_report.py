"""Assert-based smoke test for auditor.report. Run: uv run python test/test_report.py"""
from auditor.report import build, _status
from auditor.findings import finding


def test_status_kritisch_beats_mittel():
    findings = [finding("SEO-01", "MITTEL", "x", "y", solution="z"),
                finding("SEO-02", "KRITISCH", "a", "b", solution="c")]
    assert _status(findings) == "🔴"


def test_status_only_positiv_is_green():
    findings = [finding("SEO-01", "POSITIV", "x", "y")]
    assert _status(findings) == "✅"


def test_status_error_is_grey():
    assert _status([], error=True) == "⚪"


def test_build_md_renders_finding_with_solution():
    results = {
        "seo": {
            "title": "x", "title_length": 1, "meta_description": None, "meta_description_length": 0,
            "h1_tags": [], "h1_count": 0, "canonical": None, "og_title": None, "og_description": None,
            "og_image": None, "og_image_width": None, "og_image_height": None, "og_type": None,
            "twitter_card": None, "twitter_title": None, "twitter_description": None, "twitter_image": None,
            "robots_meta": None, "lang": None, "favicon_found": False, "apple_touch_icon_found": False,
            "web_app_manifest_found": False,
            "findings": [finding("SEO-04", "HOCH", "Kein Canonical-Tag vorhanden", "Wirkungstext", solution="Lösungstext")],
        }
    }
    report = build("https://x.de", results, fmt="md")
    assert "SEO-04" in report
    assert "Lösungstext" in report
    assert "| SEO | 🔴 | 1 |" in report


def test_build_json_uses_findings_key():
    results = {"seo": {"findings": [finding("SEO-01", "POSITIV", "x", "y")]}}
    report = build("https://x.de", results, fmt="json")
    assert '"findings"' in report
    assert '"issues"' not in report


if __name__ == "__main__":
    test_status_kritisch_beats_mittel()
    test_status_only_positiv_is_green()
    test_status_error_is_grey()
    test_build_md_renders_finding_with_solution()
    test_build_json_uses_findings_key()
    print("test_report: all tests passed")
