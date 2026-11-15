"""Smoke test: run_audit() must work as a silent library call — no console output, no `rich`
import in the core module. Run: uv run python test/test_runner_silent.py"""
import sys
from unittest.mock import patch
from bs4 import BeautifulSoup
from auditor import runner
from auditor.checks import seo


def test_no_rich_import_in_runner():
    assert "rich" not in sys.modules or "rich" not in runner.__dict__, \
        "runner.py must not import rich directly (keeps the library usable without the cli extra)"


def test_run_audit_silent_returns_dict():
    fake_html = "<html><head><title>t</title></head><body></body></html>"
    with patch.object(runner, "_fetch", return_value=(fake_html, {}, 42)):
        # Skip every check module — we're only proving the plumbing (no on_progress) works.
        all_checks = ["wordpress_deep", "seo", "security", "performance", "broken_links",
                      "structured_data", "markup", "legal", "tech_stack", "social",
                      "hosting", "dns", "content_quality", "a11y",
                      "ai_visibility", "contact", "accessibility_static", "reviews", "google_result"]
        results = runner.run_audit("https://tobeworks.de", skip=all_checks)
    assert isinstance(results, dict)
    assert "wordpress" in results  # only check that always runs regardless of skip


def test_on_progress_callback_fires():
    fake_html = "<html><head><title>t</title></head><body></body></html>"
    calls = []
    with patch.object(runner, "_fetch", return_value=(fake_html, {}, 42)):
        all_checks = ["wordpress_deep", "seo", "security", "performance", "broken_links",
                      "structured_data", "markup", "legal", "tech_stack", "social",
                      "hosting", "dns", "content_quality", "a11y",
                      "ai_visibility", "contact", "accessibility_static", "reviews", "google_result"]
        runner.run_audit("https://tobeworks.de", skip=all_checks, on_progress=lambda n, m: calls.append((n, m)))
    assert any(n == "start" for n, _ in calls)
    assert any(n == "done" for n, _ in calls)


def test_wordpress_result_has_findings_key():
    """Every check module (wordpress always runs regardless of skip) must expose
    'findings', not the old 'issues' — this is the cross-module contract from
    docs/superpowers/specs/2026-09-02-findings-model-and-new-checks-design.md."""
    fake_html = "<html><head><title>t</title></head><body></body></html>"
    with patch.object(runner, "_fetch", return_value=(fake_html, {}, 42)):
        all_checks = ["wordpress_deep", "seo", "security", "performance", "broken_links",
                      "structured_data", "markup", "legal", "tech_stack", "social",
                      "hosting", "dns", "content_quality", "a11y",
                      "ai_visibility", "contact", "accessibility_static", "reviews", "google_result"]
        results = runner.run_audit("https://tobeworks.de", skip=all_checks)
    assert "findings" in results["wordpress"]
    assert "issues" not in results["wordpress"]


def test_real_finding_has_all_required_fields():
    """wordpress.py's findings list is always empty, so it can't prove the *shape* of a
    Finding. seo.py on a title-less page reliably produces SEO-01 (HOCH) — check that one
    against the 7 required keys of the Finding model (auditor/findings.py)."""
    html = "<html><head></head><body><p>kein Titel</p></body></html>"
    result = seo.run("https://tobeworks.de", html, BeautifulSoup(html, "html.parser"), {})
    findings = result["findings"]
    assert findings, "seo.py must produce findings for a page without a title"
    assert any(f["id"] == "SEO-01" and f["severity"] == "HOCH" for f in findings)
    for f in findings:
        for key in ("id", "severity", "finding", "impact", "solution", "effort_days", "timeframe"):
            assert key in f, f"finding {f.get('id')} is missing required key '{key}'"
        for key in ("id", "severity", "finding", "impact"):
            assert isinstance(f[key], str) and f[key], f"{f['id']}.{key} must be a non-empty string"
        if f["severity"] != "POSITIV":
            assert isinstance(f["solution"], str) and f["solution"], f"{f['id']}.solution must be a non-empty string"


def test_soup_based_modules_run_before_content_quality():
    """content_quality entfernt nav/header/footer/script aus der gemeinsamen soup. Module, die dort nach
    Links und Skripten suchen (contact, reviews, ...), müssen vorher laufen, sonst sehen sie den Footer nicht."""
    html = ('<html><head><title>t</title></head><body><p>' + "Wort " * 30 +
            '</p><footer><a href="tel:+496131123456">anrufen</a></footer></body></html>')

    def mutating_content_quality(url, html, soup, headers):
        for tag in soup(["nav", "footer", "header", "aside", "script", "style"]):
            tag.decompose()
        return {"findings": []}

    skip = [c for c in runner_checks() if c not in ("contact", "content_quality")]
    with patch.object(runner, "_fetch", return_value=(html, {}, 42)), \
            patch.object(runner.content_quality, "run", mutating_content_quality):
        results = runner.run_audit("https://tobeworks.de", skip=skip)
    assert results["contact"]["tel_clickable"] is True


def runner_checks():
    from auditor.checks import ALL_CHECKS
    return list(ALL_CHECKS)


if __name__ == "__main__":
    test_no_rich_import_in_runner()
    test_run_audit_silent_returns_dict()
    test_on_progress_callback_fires()
    test_wordpress_result_has_findings_key()
    test_soup_based_modules_run_before_content_quality()
    test_real_finding_has_all_required_fields()
    print("test_runner_silent: all tests passed")
