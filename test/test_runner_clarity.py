"""run_audit mit und ohne clarity_judge. Abruf, Browser und Judge sind ersetzt, kein Netzzugriff.
Run: .venv/bin/python test/test_runner_clarity.py"""
from unittest.mock import patch

from auditor import runner

HTML = "<html><head><title>t</title></head><body><p>x</p></body></html>"
EVERYTHING_BUT_SEO = ["wordpress_deep", "security", "performance", "broken_links", "structured_data", "markup", "legal",
                      "tech_stack", "social", "hosting", "dns", "content_quality", "a11y", "ai_visibility", "contact",
                      "accessibility_static", "reviews", "google_result", "ux"]
FV = {"status": "ok", "title": "", "description": "", "h1": "", "text": "Websites für Zahnärzte in Mainz. Wir bauen schnelle Praxis-Websites."}
JUDGE_ANSWER = {
    "audience": {"answer": "Zahnärzte.", "quote": "Websites für Zahnärzte in Mainz"},
    "offer": {"answer": "Websites.", "quote": "schnelle Praxis-Websites"},
}


def run(skip=None, judge=None, collect=None, **kwargs):
    collect = collect or (lambda url, url_validator=None, **kw: FV)
    calls = []

    def recording_collect(url, url_validator=None, **kw):
        calls.append((url, url_validator))
        return collect(url, url_validator, **kw)

    progress = []
    with patch.object(runner, "_fetch", return_value=(HTML, {}, 42)), patch.object(runner.first_view, "collect", recording_collect):
        results = runner.run_audit("https://tobeworks.de", skip=EVERYTHING_BUT_SEO + (skip or []), clarity_judge=judge,
                                   on_progress=lambda n, m: progress.append(n), **kwargs)
    return results, calls, progress


def test_without_judge_no_browser_and_no_clarity_key():
    results, calls, _ = run()
    assert calls == [] and "clarity" not in results


def test_with_judge_clarity_runs_after_content_quality_and_reports_progress():
    results, _, progress = run(judge=lambda fv: JUDGE_ANSWER)
    assert results["clarity"]["stage"] == "klar"
    assert "clarity" in progress and progress.index("clarity") > progress.index("seo") and progress.index("clarity") < progress.index("done")
    assert "Verständlichkeit" in results["score"]["categories"]


def test_clarity_failure_does_not_break_the_audit():
    def boom(url, url_validator=None, **kw):
        raise RuntimeError("Browser kaputt")
    results, _, _ = run(judge=lambda fv: JUDGE_ANSWER, collect=boom)
    assert results["clarity"]["stage"] == "nicht_beurteilbar" and results["clarity"]["reason"] == "failed"
    assert "seo" in results and "score" in results and "Verständlichkeit" not in results["score"]["categories"]


def test_clarity_can_be_skipped():
    results, calls, _ = run(skip=["clarity"], judge=lambda fv: JUDGE_ANSWER)
    assert calls == [] and "clarity" not in results


def test_url_validator_reaches_collect():
    def validator(url):
        return True
    _, calls, _ = run(judge=lambda fv: JUDGE_ANSWER, url_validator=validator)
    assert calls == [("https://tobeworks.de", validator)]


AI_RESULT = {"blocked_crawlers": [], "llms_txt": False, "findings": [], "render": {"status": "unknown", "html_words": None, "rendered_words": None}, "checklist": []}


def run_ai(judge=None, skip=None, **kwargs):
    """Wie run(), aber ai_visibility läuft (ersetzt, kein Netz) und liefert ein eigenes Ergebnis."""
    calls = []

    def collect(url, url_validator=None, **kw):
        calls.append(url)
        return FV

    with patch.object(runner, "_fetch", return_value=(HTML, {}, 42)), patch.object(runner.first_view, "collect", collect), \
            patch.object(runner.ai_visibility, "run", return_value={**AI_RESULT, "findings": []}):
        results = runner.run_audit("https://tobeworks.de", skip=[s for s in EVERYTHING_BUT_SEO if s != "ai_visibility"] + (skip or []),
                                   clarity_judge=judge, **kwargs)
    return results, calls


def test_render_check_alone_collects_once_and_sets_render():
    results, calls = run_ai(render_check=True)
    assert len(calls) == 1 and results["ai_visibility"]["render"]["status"] == "ok" and "clarity" not in results


def test_render_check_with_judge_collects_only_once():
    results, calls = run_ai(judge=lambda fv: JUDGE_ANSWER, render_check=True)
    assert len(calls) == 1 and results["clarity"]["stage"] == "klar" and results["ai_visibility"]["render"]["status"] == "ok"


def test_neither_judge_nor_render_check_does_not_collect():
    results, calls = run_ai()
    assert calls == [] and results["ai_visibility"]["render"]["status"] == "unknown"


def test_skipping_clarity_prevents_both():
    results, calls = run_ai(judge=lambda fv: JUDGE_ANSWER, skip=["clarity"], render_check=True)
    assert calls == [] and "clarity" not in results and results["ai_visibility"]["render"]["status"] == "unknown"


def test_render_check_without_ai_visibility_does_not_raise_or_collect():
    results, calls = run_ai(skip=["ai_visibility"], render_check=True)
    assert calls == [] and "ai_visibility" not in results and "score" in results


def test_ux_shares_the_single_browser_collection_with_clarity():
    results, calls = run_ux(judge=lambda fv: JUDGE_ANSWER)
    assert len(calls) == 1 and results["clarity"]["stage"] == "klar" and results["ux"]["browser"] is True
    assert "Bedienbarkeit" in results["score"]["categories"]


def test_ux_runs_without_browser_data_when_collection_fails():
    results, calls = run_ux(collect=lambda url, url_validator=None, **kw: None)
    assert results["ux"]["browser"] is False and [f["id"] for f in results["ux"]["findings"]] == ["UXF-01"]


def run_ux(judge=None, collect=None):
    calls = []

    def default_collect(url, url_validator=None, **kw):
        calls.append(url)
        return {**FV, "mobile": {"targets": 3, "small": 0, "cta": True, "overflowX": False, "scrollWidth": 390, "width": 390}}

    use = collect or default_collect
    with patch.object(runner, "_fetch", return_value=(HTML, {}, 42)), patch.object(runner.first_view, "collect", use):
        results = runner.run_audit("https://tobeworks.de", skip=[s for s in EVERYTHING_BUT_SEO if s != "ux"], clarity_judge=judge)
    return results, calls


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
    print("test_runner_clarity: all tests passed")
