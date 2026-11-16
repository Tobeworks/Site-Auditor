"""first_view.collect gegen lokale Testseiten (127.0.0.1). Kein Test spricht mit dem Internet."""
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from auditor.checks import first_view  # noqa: E402

ALLOW_ALL = lambda url: True  # noqa: E731




def serve(pages):
    """pages: {pfad: (status, html, header-dict)}. Liefert (server, basis_url, zugriffe)."""
    hits = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append(self.path)
            status, body, headers = pages.get(self.path.split("?")[0], (404, "", {}))
            data = body.encode()
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            for key, value in headers.items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}", hits


def page(html, status=200, headers=None):
    return {"/": (status, html, headers or {})}


def collect_from(pages, **kwargs):
    server, base, hits = serve(pages)
    try:
        kwargs.setdefault("url_validator", ALLOW_ALL)
        return first_view.collect(base + "/", **kwargs), hits
    finally:
        server.shutdown()


def test_visible_text_in_viewport_is_collected():
    html = (
        "<html><head><title>Praxis-Websites</title><meta name='description' content='Schnell und klar'></head>"
        "<body><h1>Websites für Zahnärzte</h1><p>Wir bauen schnelle Praxis-Websites mit Terminbuchung.</p></body></html>"
    )
    result, _ = collect_from(page(html))
    assert result["status"] == "ok", result
    assert "Websites für Zahnärzte" in result["text"]
    assert "Terminbuchung" in result["text"]
    assert result["h1"] == "Websites für Zahnärzte"
    assert result["title"] == "Praxis-Websites"
    assert result["description"] == "Schnell und klar"


def test_text_below_the_fold_is_left_out():
    html = "<h1>Websites für Zahnärzte in Mainz</h1><div style='margin-top:2000px'>GANZ UNTEN</div>"
    result, _ = collect_from(page(html))
    assert result["status"] == "ok" and "GANZ UNTEN" not in result["text"], result


def test_hidden_and_covered_text_is_left_out():
    html = (
        "<h1>Sichtbarer Titel hier</h1>"
        "<p style='display:none'>VERSTECKT EINS</p>"
        "<p style='visibility:hidden'>VERSTECKT ZWEI</p>"
        "<p style='position:absolute;top:300px;left:10px'>UNTER OVERLAY</p>"
        "<div style='position:fixed;top:250px;left:0;width:390px;height:200px;background:#fff'>OVERLAY TEXT</div>"
    )
    result, _ = collect_from(page(html))
    for hidden in ("VERSTECKT EINS", "VERSTECKT ZWEI", "UNTER OVERLAY"):
        assert hidden not in result["text"], (hidden, result["text"])
    assert "Sichtbarer Titel hier" in result["text"] and "OVERLAY TEXT" in result["text"]


def test_consent_banner_text_is_left_out():
    html = (
        "<h1>Websites für Zahnärzte in Mainz</h1>"
        "<div id='cookie-banner' style='position:fixed;bottom:0'>Wir verwenden Cookies</div>"
    )
    result, _ = collect_from(page(html))
    assert "Wir verwenden Cookies" not in result["text"], result["text"]
    assert "Websites für Zahnärzte in Mainz" in result["text"]


def test_js_rendered_text_is_collected():
    html = (
        "<p id='x'></p><script>setTimeout(function(){document.getElementById('x').textContent="
        "'Dieser Text kommt erst per Skript nach dem Laden'},100)</script>"
    )
    result, _ = collect_from(page(html))
    assert result["status"] == "ok" and "per Skript nach dem Laden" in result["text"], result


def test_text_is_capped():
    html = "<div>" + ("wort " * 5000) + "</div>"
    result, _ = collect_from(page(html))
    assert result["status"] == "ok" and len(result["text"]) <= 4000, len(result["text"])


def test_bot_protection_is_blocked():
    result, _ = collect_from(page("<h1>Verboten für dich hier</h1>", status=403))
    assert result["status"] == "blocked", result
    result, _ = collect_from(page("<html><head><title>Just a moment...</title></head><body><p>Bitte warte einen Moment hier</p></body></html>"))
    assert result["status"] == "blocked", result


def test_empty_page_is_empty():
    result, _ = collect_from(page("<html><body></body></html>"))
    assert result["status"] == "empty", result


def test_unreachable_url_is_error():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    result = first_view.collect(f"http://127.0.0.1:{port}/", url_validator=ALLOW_ALL, timeout_s=5)
    assert result["status"] == "error", result


def test_validator_blocks_navigation_subresources_and_redirects():
    server_b, base_b, hits_b = serve({"/": (200, "<h1>Interne Seite mit genug Text</h1>", {}), "/x.png": (200, "", {})})
    port_b = server_b.server_address[1]
    allow_a = lambda url: urlparse(url).port != port_b  # noqa: E731
    server_a, base_a, _ = serve({
        "/": (200, f"<h1>Seite A mit genug Text hier</h1><img src='{base_b}/x.png'>", {}),
        "/redir": (302, "", {"Location": base_b + "/"}),
    })
    try:
        result = first_view.collect(base_a + "/", url_validator=allow_a)
        assert result["status"] == "ok", result   # ein blockiertes Bild macht die Seite nicht unlesbar
        assert hits_b == [], hits_b
        assert first_view.collect(base_b + "/", url_validator=allow_a)["status"] == "blocked"
        assert hits_b == [], hits_b
        assert first_view.collect(base_a + "/redir", url_validator=allow_a)["status"] == "blocked"
        assert hits_b == [], hits_b
    finally:
        server_a.shutdown()
        server_b.shutdown()


def test_allowed_redirect_is_followed():
    server, base, _ = serve({
        "/": (200, "<h1>Websites für Zahnärzte in Mainz</h1>", {}),
        "/old": (301, "", {"Location": "/"}),
    })
    try:
        result = first_view.collect(base + "/old", url_validator=ALLOW_ALL)
        assert result["status"] == "ok" and "Zahnärzte" in result["text"], result
    finally:
        server.shutdown()


def test_validator_verdict_is_not_shared_between_schemes():
    """Das gemerkte Ergebnis gilt je Schema und Host, sonst käme ein anderes Schema für denselben Host ungeprüft durch."""
    seen = []
    pages = {}
    server, base, _ = serve(pages)
    pages["/"] = (200, f"<h1>Websites für Zahnärzte in Mainz</h1><img src='{base.replace('http://', 'https://')}/a.png'>", {})
    try:
        first_view.collect(base + "/", url_validator=lambda u: seen.append(u) or True)
    finally:
        server.shutdown()
    assert any(u.startswith("http://127.0.0.1:") for u in seen) and any(u.startswith("https://127.0.0.1:") for u in seen), seen


def test_popups_service_workers_and_websockets_cannot_reach_internal_hosts():
    internal, base_b, hits_b = serve({"/": (200, "intern", {}), "/popup": (200, "x", {}), "/sw": (200, "x", {}), "/ws": (200, "x", {}), "/fetch": (200, "x", {})})
    pages = {}
    server, base_a, _ = serve(pages)
    base_a = base_a.replace("127.0.0.1", "localhost")   # anderer Host als der interne Server, localhost zählt als sicherer Kontext
    pages["/"] = (200, f"""<h1>Websites für Zahnärzte in Mainz und Umgebung</h1><p>eins zwei drei vier fünf sechs</p>
<script>
try {{ new WebSocket('ws://{base_b.split('//')[1]}/ws'); }} catch (e) {{}}
try {{ window.open('{base_b}/popup'); }} catch (e) {{}}
fetch('{base_b}/fetch').catch(() => {{}});
if (navigator.serviceWorker) navigator.serviceWorker.register('/sw.js').catch(() => {{}});
</script>""", {})
    pages["/sw.js"] = (200, f"self.addEventListener('install', e => e.waitUntil(fetch('{base_b}/sw', {{mode: 'no-cors'}}).catch(() => {{}})));", {"Content-Type": "application/javascript"})
    port_b = internal.server_address[1]
    try:
        result = first_view.collect(base_a + "/", url_validator=lambda u: f":{port_b}" not in u)
        time.sleep(1)
    finally:
        server.shutdown()
        internal.shutdown()
    assert result["status"] == "ok", result
    assert hits_b == [], hits_b


def test_page_that_freezes_the_browser_returns_error_and_leaves_no_browser():
    import subprocess
    count = lambda: len(subprocess.run(["pgrep", "-f", "ms-playwright"], capture_output=True, text=True).stdout.split())  # noqa: E731
    before = count()
    original = first_view._GRACE_S
    first_view._GRACE_S = 2
    html = "<h1>Websites für Zahnärzte in Mainz</h1><p>eins zwei drei vier fünf</p><script>setTimeout(function(){while(true){}}, 200)</script>"
    started = time.time()
    try:
        result, _ = collect_from(page(html), timeout_s=3)
    finally:
        first_view._GRACE_S = original
    assert result["status"] == "error", result
    assert time.time() - started < 20
    for _ in range(50):   # der Browser wird mit dem Prozess beendet, das dauert einen Moment
        if count() <= before:
            break
        time.sleep(0.2)
    assert count() <= before, (before, count())


def test_inline_elements_keep_order_and_words():
    html = "<h1>Wir bauen <span style='font-size:48px'>Websites</span>, die verkaufen.</h1><p>und noch mehr Text für Zahnärzte</p>"
    result, _ = collect_from(page(html))
    squeezed = "".join(result["text"].lower().split())
    assert "wirbauenwebsites,dieverkaufen." in squeezed, result["text"]
    assert result["text"].index("Wir bauen") < result["text"].index("Websites") < result["text"].index("verkaufen")


def test_consent_overlay_with_unknown_class_names_is_not_taken_for_the_offer():
    html = (
        "<h1>Websites für Zahnärzte in Mainz und Umgebung</h1><p>Wir bauen schnelle Praxis-Websites mit Terminbuchung für dich</p>"
        "<div class='x7q9' style='position:fixed;inset:0;background:#fff;z-index:9999'>Wir verwenden Cookies und ähnliche Technologien, "
        "um die Seite zu verbessern. Alle akzeptieren oder ablehnen.</div>"
    )
    result, _ = collect_from(page(html))
    assert "Cookies" not in result["text"]
    assert result["status"] == "empty", result


def test_unrecognised_full_screen_overlay_is_empty_not_ok():
    html = (
        "<h1>Websites für Zahnärzte in Mainz und Umgebung</h1><p>Wir bauen schnelle Praxis-Websites mit Terminbuchung für dich und "
        "betreuen sie danach jahrelang zum Festpreis ohne versteckte Kosten</p>"
        "<div class='y1' style='position:fixed;inset:0;background:#fff;z-index:9999'>Bitte wähle jetzt deine Sprache aus, bevor du weiterliest.</div>"
    )
    result, _ = collect_from(page(html))
    assert result["status"] == "empty", result


def test_fixed_header_does_not_hide_the_hero():
    html = (
        "<div style='position:fixed;top:0;left:0;right:0;height:50px;background:#fff'>Startseite Leistungen Kontakt</div>"
        "<h1 style='margin-top:80px'>Websites für Zahnärzte in Mainz und Umgebung</h1><p>Wir bauen schnelle Praxis-Websites</p>"
    )
    result, _ = collect_from(page(html))
    assert result["status"] == "ok" and "Zahnärzte" in result["text"], result


def test_validator_runs_in_the_parent_process():
    """Die Namensauflösung des Validators darf nicht im geforkten Kindprozess laufen (auf macOS unzuverlässig)."""
    import os
    pids = []

    def validator(u):
        pids.append(os.getpid())
        return True
    html = "<h1>Websites für Zahnärzte in Mainz und Umgebung</h1><p>eins zwei drei vier fünf sechs</p>"
    result, _ = collect_from(page(html), url_validator=validator)
    assert result["status"] == "ok" and pids and set(pids) == {os.getpid()}, (result, pids)


def test_full_browser_pool_returns_error():
    original = first_view._BROWSERS, first_view._WAIT_S
    first_view._BROWSERS = threading.BoundedSemaphore(1)
    first_view._BROWSERS.acquire()
    first_view._WAIT_S = 0.2
    try:
        result, _ = collect_from(page("<h1>Websites für Zahnärzte in Mainz</h1>"))
        assert result["status"] == "error", result
    finally:
        first_view._BROWSERS, first_view._WAIT_S = original


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
    print("test_first_view: all tests passed")
