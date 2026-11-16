"""Sichtbarer Text des ersten Handy-Bildschirms einer Seite. Bewertet nichts, liefert nur Daten für `clarity`.

Öffnet die Seite mit Playwright (Chromium, Viewport 390 mal 844) und sammelt den Text, der im Viewport liegt, sichtbar
und nicht verdeckt ist und nicht zu einem Einwilligungsbanner gehört. Jede Anfrage des Browsers geht durch
`url_validator`, damit ein öffentlicher Dienst nicht auf interne Adressen zugreifen lässt. Wirft nie.
"""
import threading
from typing import Callable
from urllib.parse import urljoin, urlparse

VIEWPORT = {"width": 390, "height": 844}
MAX_TEXT = 4000
MIN_WORDS = 5
BLOCKED_STATUS = (403, 429, 503)
BLOCKED_TITLES = ("just a moment", "attention required", "access denied", "checking your browser")
IDLE_WAIT_MS = 3000
MAX_REDIRECTS = 5
REDIRECT_STATUS = (301, 302, 303, 307, 308)

_BROWSERS = threading.BoundedSemaphore(2)  # gleichzeitige Browser je Prozess, damit die Gunicorn-Worker den Speicher nicht sprengen
_WAIT_S = 20  # so lange wartet ein Aufruf auf einen freien Browser

# Textknoten im Viewport, sichtbar, nicht verdeckt und nicht in einem Einwilligungsbanner
_COLLECT_JS = """
() => {
  const consent = /cookie|consent|gdpr|usercentrics|onetrust|(^|[-_\\s])cmp([-_\\s]|$)/i;
  const skip = new Set(["SCRIPT", "STYLE", "NOSCRIPT", "TEMPLATE"]);
  const vw = window.innerWidth, vh = window.innerHeight;
  const pieces = [];
  const walker = document.createTreeWalker(document.body || document.documentElement, NodeFilter.SHOW_TEXT);
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    const text = node.nodeValue.replace(/\\s+/g, " ").trim();
    const el = node.parentElement;
    if (!text || !el || skip.has(el.tagName)) continue;
    const range = document.createRange();
    range.selectNodeContents(node);
    const rect = range.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) continue;
    if (rect.bottom <= 0 || rect.top >= vh || rect.right <= 0 || rect.left >= vw) continue;
    let hidden = false, banner = false;
    for (let a = el; a; a = a.parentElement) {
      const s = getComputedStyle(a);
      if (s.display === "none" || s.visibility === "hidden" || parseFloat(s.opacity) === 0) { hidden = true; break; }
      if (consent.test((a.id || "") + " " + (a.getAttribute("class") || ""))) { banner = true; break; }
    }
    if (hidden || banner) continue;
    const x = Math.min(Math.max((rect.left + rect.right) / 2, 0), vw - 1);
    const y = Math.min(Math.max((rect.top + rect.bottom) / 2, 0), vh - 1);
    const top = document.elementFromPoint(x, y);
    if (!top || !(top === el || el.contains(top))) continue;
    pieces.push({top: Math.round(rect.top), left: Math.round(rect.left), text});
  }
  pieces.sort((p, q) => p.top - q.top || p.left - q.left);
  const h1 = document.querySelector("h1");
  const meta = document.querySelector("meta[name=description]");
  return {
    text: pieces.map(p => p.text).join(" "),
    h1: h1 ? h1.innerText.replace(/\\s+/g, " ").trim() : "",
    description: meta ? (meta.getAttribute("content") || "").trim() : "",
  };
}
"""


def _result(status: str, title: str = "", description: str = "", h1: str = "", text: str = "") -> dict:
    return {"status": status, "title": title, "description": description, "h1": h1, "text": text}


def collect(url: str, url_validator: Callable[[str], bool] | None = None, timeout_s: float = 25) -> dict:
    if not _BROWSERS.acquire(timeout=_WAIT_S):
        return _result("error")
    try:
        return _collect(url, url_validator, timeout_s)
    except Exception:
        return _result("error")
    finally:
        _BROWSERS.release()


def _collect(url: str, url_validator, timeout_s: float) -> dict:
    from playwright.sync_api import sync_playwright

    state = {"blocked": False, "redirect": None}
    verdicts: dict[str, bool] = {}  # je Host nur einmal prüfen, die Prüfung löst DNS auf

    def allowed(request_url: str) -> bool:
        if url_validator is None:
            return True
        host = urlparse(request_url).netloc
        if host not in verdicts:
            try:
                verdicts[host] = bool(url_validator(request_url))
            except Exception:
                verdicts[host] = False
        return verdicts[host]

    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])  # /dev/shm ist im Container oft nur 64 MB groß
        try:
            # ohne is_mobile, sonst layoutet Chromium Seiten ohne Viewport-Meta mit 980 Pixeln Breite
            context = browser.new_context(viewport=VIEWPORT, has_touch=True)
            page = context.new_page()

            def fetch_checked(route, request_url):
                """Folgt Weiterleitungen selbst, denn der Browser meldet Weiterleitungsziele nicht an `page.route`.
                Liefert (Antwort, Endadresse) oder None, wenn ein Ziel nicht erlaubt ist oder es zu viele Sprünge gibt."""
                current = request_url
                for _ in range(MAX_REDIRECTS + 1):
                    response = route.fetch(url=current, max_redirects=0)
                    location = response.headers.get("location")
                    if response.status not in REDIRECT_STATUS or not location:
                        return response, current
                    current = urljoin(current, location)
                    if not allowed(current):
                        return None
                return None

            def handle(route):
                request = route.request
                is_document = request.is_navigation_request() and request.frame == page.main_frame
                try:
                    if request.url.split(":", 1)[0].lower() in ("data", "blob", "about"):
                        route.continue_()
                    elif request.resource_type == "media" or not allowed(request.url):
                        state["blocked"] = state["blocked"] or (is_document and not allowed(request.url))
                        route.abort()
                    else:
                        checked = fetch_checked(route, request.url)
                        if checked is None:
                            state["blocked"] = state["blocked"] or is_document
                            route.abort()
                        elif is_document and checked[1] != request.url:
                            state["redirect"] = checked[1]  # neu laden, damit relative Adressen zur Endadresse passen
                            route.fulfill(status=200, content_type="text/html", body="")  # abort ließe eine Fehlerseite nachladen
                        else:
                            route.fulfill(response=checked[0])
                except Exception:
                    route.abort()

            # ponytail: die Adresse, die der Browser auflöst, kann von der Prüfung abweichen (DNS-Rebinding), bekannte Grenze
            page.route("**/*", handle)
            response = None
            target = url
            for _ in range(MAX_REDIRECTS + 1):
                state["redirect"] = None
                try:
                    response = page.goto(target, wait_until="load", timeout=timeout_s * 1000)
                except Exception:
                    return _result("blocked" if state["blocked"] else "error")
                if not state["redirect"] or state["blocked"]:
                    break
                target = state["redirect"]
            else:
                return _result("error")
            if state["blocked"]:
                return _result("blocked")
            try:
                page.wait_for_load_state("networkidle", timeout=IDLE_WAIT_MS)
            except Exception:
                pass  # nicht fatal, manche Seiten haben nie Netzwerkruhe
            title = page.title().strip()
            if (response and response.status in BLOCKED_STATUS) or any(t in title.lower() for t in BLOCKED_TITLES):
                return _result("blocked", title=title)
            data = page.evaluate(_COLLECT_JS)
        finally:
            browser.close()

    text = data["text"][:MAX_TEXT]
    status = "ok" if len(text.split()) >= MIN_WORDS else "empty"
    return _result(status, title=title, description=data["description"], h1=data["h1"], text=text)
