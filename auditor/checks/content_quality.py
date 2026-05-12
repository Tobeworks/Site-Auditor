import asyncio
import re
import httpx
from bs4 import BeautifulSoup
from urllib.parse import urljoin


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


def run(url: str, html: str, soup: BeautifulSoup, headers: dict) -> dict:
    try:
        issues = []

        # Visible text (exclude nav, footer, header, aside)
        for tag in soup(["nav", "footer", "header", "aside", "script", "style"]):
            tag.decompose()
        text = soup.get_text(separator=" ")
        words = text.split()
        word_count = len(words)

        thin_content = word_count < 300

        # Title vs H1 duplicate
        title_tag = soup.find("title")
        title_text = title_tag.get_text(strip=True) if title_tag else ""
        h1_tag = soup.find("h1")
        h1_text = h1_tag.get_text(strip=True) if h1_tag else ""
        title_equals_h1 = bool(title_text and title_text == h1_text)

        # Readability (avg sentence length)
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

        # Broken images (async parallel)
        img_tags = soup.find_all("img", src=True)
        img_srcs = []
        for img in img_tags[:20]:
            src = img.get("src", "")
            if src.startswith("http"):
                img_srcs.append(src)
            elif src.startswith("/"):
                from urllib.parse import urlparse
                base = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
                img_srcs.append(f"{base}{src}")

        broken_images = asyncio.run(_check_images(img_srcs))

        # Issues
        if thin_content:
            issues.append(f"Thin Content: nur {word_count} Wörter (Minimum 300 empfohlen)")
        if title_equals_h1:
            issues.append("Title und H1 sind identisch (für Abwechslung sorgen)")
        if avg_sentence_length > 25:
            issues.append(f"Durchschnittliche Satzlänge sehr hoch ({avg_sentence_length} Wörter)")
        if broken_images:
            issues.append(f"{len(broken_images)} defekte(s) Bild(er) gefunden")

        return {
            "word_count": word_count,
            "thin_content": thin_content,
            "title_equals_h1": title_equals_h1,
            "avg_sentence_length": avg_sentence_length,
            "readability_hint": readability_hint,
            "broken_images": broken_images,
            "issues": issues,
        }
    except Exception as e:
        return {"error": str(e)}
