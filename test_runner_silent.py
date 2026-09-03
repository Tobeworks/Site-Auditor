"""Smoke test: run_audit() must work as a silent library call — no console output, no `rich`
import in the core module. Run: python test_runner_silent.py"""
import sys
from unittest.mock import patch
from auditor import runner


def test_no_rich_import_in_runner():
    assert "rich" not in sys.modules or "rich" not in runner.__dict__, \
        "runner.py must not import rich directly (keeps the library usable without the cli extra)"


def test_run_audit_silent_returns_dict():
    fake_html = "<html><head><title>t</title></head><body></body></html>"
    with patch.object(runner, "_fetch", return_value=(fake_html, {}, 42)):
        # Skip every check module — we're only proving the plumbing (no on_progress) works.
        all_checks = ["wordpress_deep", "seo", "security", "performance", "broken_links",
                      "structured_data", "markup", "legal", "tech_stack", "social",
                      "hosting", "dns", "content_quality", "a11y"]
        results = runner.run_audit("https://tobeworks.de", skip=all_checks)
    assert isinstance(results, dict)
    assert "wordpress" in results  # only check that always runs regardless of skip


def test_on_progress_callback_fires():
    fake_html = "<html><head><title>t</title></head><body></body></html>"
    calls = []
    with patch.object(runner, "_fetch", return_value=(fake_html, {}, 42)):
        all_checks = ["wordpress_deep", "seo", "security", "performance", "broken_links",
                      "structured_data", "markup", "legal", "tech_stack", "social",
                      "hosting", "dns", "content_quality", "a11y"]
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
                      "hosting", "dns", "content_quality", "a11y"]
        results = runner.run_audit("https://tobeworks.de", skip=all_checks)
    assert "findings" in results["wordpress"]
    assert "issues" not in results["wordpress"]


if __name__ == "__main__":
    test_no_rich_import_in_runner()
    test_run_audit_silent_returns_dict()
    test_on_progress_callback_fires()
    test_wordpress_result_has_findings_key()
    print("test_runner_silent: all tests passed")
