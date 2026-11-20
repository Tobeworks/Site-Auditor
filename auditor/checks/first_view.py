"""Sichtbarer Text des ersten Handy-Bildschirms einer Seite. Bewertet nichts, liefert nur Daten für `clarity`.

Öffnet die Seite mit Playwright (Chromium, Viewport 390 mal 844) und sammelt den Text, der im Viewport liegt, sichtbar
und nicht verdeckt ist und nicht zu einem Einwilligungsbanner gehört. Jede Anfrage des Browsers geht durch
`url_validator`, damit ein öffentlicher Dienst nicht auf interne Adressen zugreifen lässt. Wirft nie.
"""
import hashlib
import multiprocessing
import threading
import time
from typing import Callable
from urllib.parse import urljoin, urlparse

import httpx

VIEWPORT = {"width": 390, "height": 844}
MAX_TEXT = 4000
MIN_WORDS = 5
BLOCKED_STATUS = (403, 429, 503)
BLOCKED_TITLES = ("just a moment", "attention required", "access denied", "checking your browser")
IDLE_WAIT_MS = 3000
MAX_REDIRECTS = 5
REDIRECT_STATUS = (301, 302, 303, 307, 308)

# axe-core für die Barrierefreiheitsprüfung. Wird einmal geladen und gegen den Hash geprüft, dann ohne Netz in die Seite gegeben.
AXE_URL = "https://cdnjs.cloudflare.com/ajax/libs/axe-core/4.9.1/axe.min.js"
AXE_SHA256 = "182a40dc5d8207e626c09861ad65027d45e85e3a56d01045d068e2e88ee432ea"
AXE_TIMEOUT_MS = 25000  # auf großen Seiten braucht axe mehrere Sekunden, im Container mehr als lokal
SETTLE_MS = 3000
# Nur das, was a11y braucht, damit nicht das ganze DOM durch die Verbindung muss
_AXE_JS = """
() => Promise.race([
  axe.run({resultTypes: ["violations", "incomplete"]}),  // passes und inapplicable bleiben weg, das spart viel Rechenzeit
  new Promise((_, reject) => setTimeout(() => reject(new Error("axe timeout")), %d)),
]).then((r) => ({
  violations: r.violations.map((v) => ({id: v.id, impact: v.impact, tags: v.tags, description: v.description, nodes: v.nodes.map((n) => ({target: n.target}))})),
  incomplete: r.incomplete.slice(0, 10).map((v) => ({id: v.id, description: v.description})),
}))
""" % AXE_TIMEOUT_MS
_SETTLE_JS = """
() => Promise.race([
  Promise.all(document.getAnimations().filter((a) => a.effect && a.effect.getComputedTiming().iterations !== Infinity).map((a) => a.finished.catch(() => {}))),
  new Promise((resolve) => setTimeout(resolve, %d)),
]).then(() => 0)
""" % SETTLE_MS
# Handy-Signale des ersten Bildschirms für das Modul ux: seitliches Scrollen, Weg zum Handeln im Viewport, zu kleine Tippflächen (WCAG 2.5.8: 24 px)
_MOBILE_JS = """
() => {
  const vw = window.innerWidth, vh = window.innerHeight;
  const doc = document.documentElement;
  const shown = (el) => {
    const r = el.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0 || r.bottom <= 0 || r.top >= vh || r.right <= 0 || r.left >= vw) return null;
    const s = getComputedStyle(el);
    return s.display === "none" || s.visibility === "hidden" || parseFloat(s.opacity) === 0 ? null : r;
  };
  const action = /anfrage|kontakt|termin|angebot|anruf|beratung|buchen|bestell|kaufen|gespräch|starten|testen|contact|book|call|buy|order|quote|get started|get in touch/i;
  let targets = 0, small = 0, cta = false;
  for (const el of document.querySelectorAll("a[href], button, input:not([type=hidden]), select, textarea, [role=button]")) {
    const r = shown(el);
    if (!r) continue;
    targets++;
    const inline = el.tagName === "A" && getComputedStyle(el).display === "inline";  // Links im Fließtext sind ausgenommen
    if ((r.width < 24 || r.height < 24) && !inline) small++;
    const href = (el.getAttribute("href") || "").toLowerCase();
    if (href.startsWith("tel:") || href.startsWith("mailto:") || ["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName)
        || action.test((el.innerText || "") + " " + href)) cta = true;
  }
  const clipped = ["hidden", "clip"].includes(getComputedStyle(doc).overflowX) || ["hidden", "clip"].includes(getComputedStyle(document.body).overflowX);
  return {targets, small, cta, overflowX: doc.scrollWidth > vw + 1 && !clipped, scrollWidth: doc.scrollWidth, width: vw};
}
"""
_axe_source: str | None = None

_BROWSERS = threading.BoundedSemaphore(2)  # gleichzeitige Browser je Prozess, damit die Gunicorn-Worker den Speicher nicht sprengen
_WAIT_S = 20  # so lange wartet ein Aufruf auf einen freien Browser
_GRACE_S = 15  # Zeit über timeout_s und Netzwerkruhe hinaus, dann wird der Browserprozess beendet
OVERLAY_MIN_COVERED_WORDS = 15  # so viele verdeckte Wörter, dann gilt ein Vollbild-Overlay als Grund für "kein Text"

# Textknoten im Viewport, sichtbar, nicht verdeckt und nicht in einem Einwilligungsbanner. Die Knoten bleiben in DOM-Reihenfolge und
# werden je Blockelement zusammengefasst, damit Wörter in Inline-Elementen (<span>, <strong>) nicht aus dem Satz rutschen.
_COLLECT_JS = """
() => {
  const consentName = /cookie|consent|gdpr|usercentrics|onetrust|(^|[-_\\s])cmp([-_\\s]|$)/i;
  const consentText = /cookie|einwillig|consent|akzeptier|ablehn|accept|tracking|datenschutz|privacy/i;
  const skip = new Set(["SCRIPT", "STYLE", "NOSCRIPT", "TEMPLATE"]);
  const vw = window.innerWidth, vh = window.innerHeight;
  const blocks = new Map();
  let coveredWords = 0, keptWords = 0, fixedWords = 0;
  const words = (t) => t.split(" ").filter(Boolean).length;
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
    let hidden = false, banner = false, fixed = false, block = null;
    for (let a = el; a; a = a.parentElement) {
      const s = getComputedStyle(a);
      if (s.display === "none" || s.visibility === "hidden" || parseFloat(s.opacity) === 0) { hidden = true; break; }
      if (consentName.test((a.id || "") + " " + (a.getAttribute("class") || ""))) { banner = true; break; }
      if (s.position === "fixed" || s.position === "sticky") {
        fixed = true;
        // Overlay mit unbekannten Klassennamen, aber Einwilligungs-Wortlaut
        if (consentText.test(a.innerText || "")) { banner = true; break; }
      }
      if (!block && !s.display.startsWith("inline") && s.display !== "contents") block = a;
    }
    if (hidden || banner) continue;
    const x = Math.min(Math.max((rect.left + rect.right) / 2, 0), vw - 1);
    const y = Math.min(Math.max((rect.top + rect.bottom) / 2, 0), vh - 1);
    const top = document.elementFromPoint(x, y);
    if (!top || !(top === el || el.contains(top))) { coveredWords += words(text); continue; }
    keptWords += words(text);
    if (fixed) fixedWords += words(text);
    const key = block || el;
    if (!blocks.has(key)) blocks.set(key, {top: Math.round(rect.top), left: Math.round(rect.left), texts: []});
    blocks.get(key).texts.push(text);
  }
  const ordered = [...blocks.values()].sort((p, q) => p.top - q.top || p.left - q.left);
  const h1 = document.querySelector("h1");
  const meta = document.querySelector("meta[name=description]");
  return {
    text: ordered.map(b => b.texts.join(" ")).join(" "),
    coveredWords, keptWords, fixedWords,
    h1: h1 ? h1.innerText.replace(/\\s+/g, " ").trim() : "",
    description: meta ? (meta.getAttribute("content") || "").trim() : "",
  };
}
"""


def _result(status: str, title: str = "", description: str = "", h1: str = "", text: str = "") -> dict:
    return {"status": status, "title": title, "description": description, "h1": h1, "text": text}


def _load_axe() -> str | None:
    """axe-core aus dem Netz holen und nur mit passendem Hash verwenden. None, wenn es nicht klappt (nächster Versuch beim nächsten Aufruf)."""
    global _axe_source
    if _axe_source is None:
        try:
            r = httpx.get(AXE_URL, timeout=10, follow_redirects=False)
        except Exception:
            return None
        ok = r.status_code == 200 and hashlib.sha256(r.content).hexdigest() == AXE_SHA256
        _axe_source = r.text if ok else ""
    return _axe_source or None


def collect(url: str, url_validator: Callable[[str], bool] | None = None, timeout_s: float = 25, axe: bool = False) -> dict:
    """axe=True: führt in derselben geschützten Browsersitzung axe-core aus, Ergebnis unter "axe" (None, wenn es nicht lief)."""
    if not _BROWSERS.acquire(timeout=_WAIT_S):
        return _result("error")
    try:
        return _collect_isolated(url, url_validator, timeout_s, _load_axe() if axe else None)
    except Exception:
        return _result("error")
    finally:
        _BROWSERS.release()


def _collect_isolated(url: str, url_validator, timeout_s: float, axe_source: str | None = None) -> dict:
    """Läuft in einem eigenen Prozess, der nach Ablauf der Frist hart beendet wird. Eine Seite, die ihren Haupt-Thread blockiert
    (Endlosschleife), lässt page.title() und page.evaluate() sonst ewig warten und hält Browser und Platz im Pool fest.
    Mit dem Prozess endet auch der Playwright-Treiber und damit der Browser.

    Der url_validator läuft im Elternprozess: Das Kind schickt jede Adresse über die Verbindung und bekommt ein Ja oder Nein.
    So wird der Validator nicht übertragen (Closures gehen) und die Namensauflösung findet nicht in einem geforkten Prozess statt,
    wo sie auf macOS nicht zuverlässig ist."""
    ctx = multiprocessing.get_context("fork")
    mine, theirs = ctx.Pipe(duplex=True)
    proc = ctx.Process(target=_child, args=(theirs, url, url_validator is not None, timeout_s, axe_source), daemon=True)
    proc.start()
    theirs.close()
    deadline = time.monotonic() + timeout_s + IDLE_WAIT_MS / 1000 + _GRACE_S + ((AXE_TIMEOUT_MS + SETTLE_MS) / 1000 if axe_source else 0)
    try:
        while True:
            left = deadline - time.monotonic()
            if left <= 0 or not mine.poll(left):
                return _result("error")
            kind, payload = mine.recv()
            if kind == "result":
                return payload
            if kind == "validate":
                try:
                    allowed = bool(url_validator(payload))
                except Exception:
                    allowed = False
                mine.send(allowed)
    except (EOFError, OSError):
        return _result("error")
    finally:
        proc.terminate()
        proc.join(5)
        if proc.is_alive():
            proc.kill()
            proc.join()
        mine.close()


def _child(conn, url, has_validator, timeout_s, axe_source=None) -> None:
    def ask(request_url: str) -> bool:
        conn.send(("validate", request_url))
        return bool(conn.recv())

    try:
        result = _collect(url, ask if has_validator else None, timeout_s, axe_source)
    except Exception:
        result = _result("error")
    conn.send(("result", result))
    conn.close()


def _collect(url: str, url_validator, timeout_s: float, axe_source: str | None = None) -> dict:
    from playwright.sync_api import sync_playwright

    state = {"blocked": False, "redirect": None}
    verdicts: dict[tuple[str, str], bool] = {}  # je Schema und Host nur einmal prüfen, die Prüfung löst DNS auf

    def allowed(request_url: str) -> bool:
        if url_validator is None:
            return True
        parsed = urlparse(request_url)
        key = (parsed.scheme, parsed.netloc)  # je Schema und Host, ein anderes Schema darf nicht vom Ergebnis eines anderen profitieren
        if key not in verdicts:
            try:
                verdicts[key] = bool(url_validator(request_url))
            except Exception:
                verdicts[key] = False
        return verdicts[key]

    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])  # /dev/shm ist im Container oft nur 64 MB groß
        try:
            # ohne is_mobile, sonst layoutet Chromium Seiten ohne Viewport-Meta mit 980 Pixeln Breite
            # Service Worker blockieren: ihre Anfragen laufen an page.route vorbei
            context = browser.new_context(viewport=VIEWPORT, has_touch=True, service_workers="block")
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
                try:
                    # request.frame wirft bei Anfragen, die vor dem Frame entstehen (Popups), dann ist es nicht das Hauptdokument
                    try:
                        is_document = request.is_navigation_request() and request.frame == page.main_frame
                    except Exception:
                        is_document = False
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
            # Routing am Kontext, damit auch Popups und alle weiteren Seiten durch dieselbe Prüfung gehen. Popups werden zusätzlich
            # geschlossen, WebSockets bleiben Attrappen (page.route sieht beides nicht).
            context.route("**/*", handle)
            context.route_web_socket("**/*", lambda ws: None)  # ohne connect_to_server bleibt die Verbindung eine Attrappe, es geht nichts ans Netz
            context.on("page", lambda popup: popup.close() if popup != page else None)
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
            # Einblend-Animationen abwarten, sonst messen axe und die Handy-Signale mitten im Überblenden (falsche Kontraste, unsichtbare Buttons)
            try:
                page.evaluate(_SETTLE_JS)
            except Exception:
                pass
            try:
                mobile = page.evaluate(_MOBILE_JS)
            except Exception:
                mobile = None
            axe_results = None
            if axe_source:
                try:
                    # evaluate statt Script-Tag: Eine Content-Security-Policy der Seite blockiert eingefügte Skripte, nicht aber evaluate
                    page.evaluate(axe_source + "\n;0")
                    axe_results = page.evaluate(_AXE_JS)
                except Exception:
                    axe_results = None
        finally:
            browser.close()

    text = data["text"][:MAX_TEXT]
    status = "ok" if len(text.split()) >= MIN_WORDS else "empty"
    # Ein Vollbild-Overlay (Einwilligung mit unbekanntem Aufbau, Sprachwahl) deckt die Seite ab: Der Text stammt dann fast nur
    # aus dem Overlay. Das ist kein Befund über die Seite, also "kein Text" statt "unklar".
    if data["coveredWords"] >= OVERLAY_MIN_COVERED_WORDS and data["fixedWords"] * 2 >= data["keptWords"]:
        status, text = "empty", ""
    result = _result(status, title=title, description=data["description"], h1=data["h1"], text=text)
    result["mobile"] = mobile
    if axe_source:
        result["axe"] = axe_results
    return result
