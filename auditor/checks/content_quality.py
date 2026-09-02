import asyncio
import re
import uuid
import httpx
from bs4 import BeautifulSoup
from urllib.parse import urlparse

from auditor.findings import finding


async def _check_images(srcs: list[str]) -> list[dict]:
    broken = []
    semaphore = asyncio.Semaphore(10)

    async def check(src):
        async with semaphore:
            try:
                async with httpx.AsyncClient(timeout=5, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"}) as client:
                    r = await client.head(src)
                    if r.status_code >= 400:
                        broken.append({"src": src, "status": r.status_code})
            except Exception:
                broken.append({"src": src, "status": 0})

    await asyncio.gather(*[check(s) for s in srcs])
    return broken


def _check_soft_404(url: str, current_page_text_len: int) -> dict | None:
    """GET a guaranteed-nonexistent URL and judge the 404 page's quality. Returns
    None if the request itself failed (network hiccup — don't flag on that)."""
    base = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
    probe_url = f"{base}/site-auditor-404-check-{uuid.uuid4().hex[:12]}"
    try:
        r = httpx.get(probe_url, timeout=8, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"})
    except Exception:
        return None

    if r.status_code == 200:
        return {"soft_404": True}

    if r.status_code in (404, 410):
        error_soup = BeautifulSoup(r.text, "lxml")
        has_nav = error_soup.find(["nav", "header"]) is not None
        error_text_len = len(error_soup.get_text(separator=" ").split())
        ratio = error_text_len / current_page_text_len if current_page_text_len else 0
        generic = ratio < 0.2 and not has_nav
        return {"soft_404": False, "generic": generic}

    return None


def run(url: str, html: str, soup: BeautifulSoup, headers: dict) -> dict:
    try:
        findings = []

        for tag in soup(["nav", "footer", "header", "aside", "script", "style"]):
            tag.decompose()
        text = soup.get_text(separator=" ")
        words = text.split()
        word_count = len(words)
        thin_content = word_count < 300

        title_tag = soup.find("title")
        title_text = title_tag.get_text(strip=True) if title_tag else ""
        h1_tag = soup.find("h1")
        h1_text = h1_tag.get_text(strip=True) if h1_tag else ""
        title_equals_h1 = bool(title_text and title_text == h1_text)

        sentences = re.split(r"[.!?]+", text)
        sentences = [s.strip() for s in sentences if len(s.strip()) > 10]
        avg_sentence_length = round(sum(len(s.split()) for s in sentences) / max(len(sentences), 1), 1)

        if avg_sentence_length < 10:
            readability_hint = "Sehr einfach (kurze Sätze)"
        elif avg_sentence_length < 20:
            readability_hint = "Gut lesbar"
        elif avg_sentence_length < 30:
            readability_hint = "Mittelschwer"
        else:
            readability_hint = "Schwer lesbar (sehr lange Sätze)"

        img_tags = soup.find_all("img", src=True)
        img_srcs = []
        for img in img_tags[:20]:
            src = img.get("src", "")
            if src.startswith("http"):
                img_srcs.append(src)
            elif src.startswith("/"):
                base = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
                img_srcs.append(f"{base}{src}")

        broken_images = asyncio.run(_check_images(img_srcs)) if img_srcs else []

        soft_404_result = _check_soft_404(url, word_count)

        # CNT-01 Thin Content
        if thin_content:
            findings.append(finding("CNT-01", "MITTEL", f"Thin Content: nur {word_count} Wörter (Minimum 300 empfohlen)",
                "Sehr kurze Seiten liefern Suchmaschinen wenig thematisches Signal und ranken tendenziell schlechter.",
                solution="Inhalt auf mindestens 300 Wörter erweitern, mit für den Nutzer relevanten Informationen."))
        else:
            findings.append(finding("CNT-01", "POSITIV", f"Ausreichend Textinhalt ({word_count} Wörter)",
                "Genug thematisches Signal für Suchmaschinen vorhanden."))

        # CNT-02 Title = H1
        if title_text and h1_text:
            if title_equals_h1:
                findings.append(finding("CNT-02", "MITTEL", "Title und H1 sind identisch",
                    "Identischer Title/H1 verschenkt die Chance, in beiden unterschiedliche relevante Keywords/Formulierungen unterzubringen.",
                    solution="Title und H1 unterschiedlich formulieren (z.B. Title mit Marke/Nutzenversprechen, H1 thema-fokussiert)."))
            else:
                findings.append(finding("CNT-02", "POSITIV", "Title und H1 sind unterschiedlich formuliert",
                    "Beide Elemente können unabhängig für Klickrate bzw. Seitenthema optimiert werden."))

        # CNT-03 Lesbarkeit
        if avg_sentence_length > 25:
            findings.append(finding("CNT-03", "MITTEL", f"Durchschnittliche Satzlänge sehr hoch ({avg_sentence_length} Wörter)",
                "Sehr lange Sätze erschweren das Lesen, besonders auf Mobilgeräten und für Nutzer mit Leseschwäche.",
                solution="Lange Sätze in mehrere kurze Sätze aufteilen."))
        else:
            findings.append(finding("CNT-03", "POSITIV", f"Lesbarkeit: {readability_hint}",
                "Durchschnittliche Satzlänge liegt in einem gut lesbaren Bereich."))

        # CNT-04 defekte Bilder
        if img_srcs:
            if broken_images:
                findings.append(finding("CNT-04", "MITTEL", f"{len(broken_images)} defekte(s) Bild(er) gefunden",
                    "Defekte Bilder wirken unprofessionell und können Nutzer und Suchmaschinen-Crawler gleichermaßen stören.",
                    solution="Defekte Bildpfade korrigieren oder die betroffenen <img>-Tags entfernen."))
            else:
                findings.append(finding("CNT-04", "POSITIV", "Keine defekten Bilder gefunden",
                    "Alle geprüften Bilder laden erfolgreich."))

        # CNT-05 Soft-404-Qualität
        if soft_404_result is not None:
            if soft_404_result["soft_404"]:
                findings.append(finding("CNT-05", "HOCH", "Soft-404: nicht existierende URL liefert HTTP 200 statt 404/410",
                    "Suchmaschinen erkennen nicht-existierende Seiten nicht als solche — kann zu Duplicate-Content und verschwendetem Crawl-Budget führen.",
                    solution="Server so konfigurieren, dass nicht existierende URLs einen echten 404- oder 410-Statuscode liefern."))
            elif soft_404_result["generic"]:
                findings.append(finding("CNT-05", "MITTEL", "404-Seite wirkt generisch (kein eigenes Branding/Navigation erkennbar)",
                    "Eine generische Fehlerseite ohne Navigation lässt Besucher auf einer Sackgasse zurück, statt sie zurück ins Angebot zu führen.",
                    solution="Eine eigene 404-Seite mit Navigation, Suchfeld und Branding gestalten."))
            else:
                findings.append(finding("CNT-05", "POSITIV", "404-Seite ist eigenständig gestaltet (Navigation/Branding vorhanden)",
                    "Besucher können von der Fehlerseite aus zurück ins Angebot navigieren."))

        return {
            "word_count": word_count,
            "thin_content": thin_content,
            "title_equals_h1": title_equals_h1,
            "avg_sentence_length": avg_sentence_length,
            "readability_hint": readability_hint,
            "broken_images": broken_images,
            "findings": findings,
        }
    except Exception as e:
        return {"error": str(e)}
