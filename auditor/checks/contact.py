import re
from bs4 import BeautifulSoup

from auditor.findings import finding

# Deutsche Rufnummer: Vorwahl +49/0049/0, dann mindestens 7 weitere Ziffern (Leerzeichen, - / ( ) erlaubt).
PHONE_RE = re.compile(r"(?<![\d.])(?:\+49|0049|0)[\s\-/()]*\d(?:[\s\-/()]*\d){6,13}(?![\d.])")
FORM_PROVIDERS = ("typeform", "hsforms", "hubspot", "calendly", "cal.com", "jotform", "tally.so")
MIN_WORDS = 20  # darunter ist die Seite vermutlich per JavaScript gerendert


def _visible_text(soup: BeautifulSoup) -> str:
    skip = {"script", "style", "noscript", "head", "title"}
    return " ".join(t.strip() for t in soup.find_all(string=True) if t.parent and t.parent.name not in skip and t.strip())


def _has_contact_form(soup: BeautifulSoup) -> bool:
    for form in soup.find_all("form"):
        if form.get("role") == "search" or form.find("input", attrs={"type": "search"}):
            continue
        if form.find("textarea") or form.find("input", attrs={"type": "email"}):
            return True
    return False


def run(url: str, html: str, soup: BeautifulSoup, headers: dict) -> dict:
    try:
        links = soup.find_all("a", href=True)
        hrefs = [a["href"].strip().lower() for a in links]
        text = _visible_text(soup)

        tel_clickable = any(h.startswith("tel:") for h in hrefs)
        has_tel = tel_clickable or bool(PHONE_RE.search(text))
        has_mail = any(h.startswith("mailto:") for h in hrefs)
        has_provider = any(
            any(p in (s.get("src") or "").lower() for p in FORM_PROVIDERS) for s in soup.find_all("script")
        )
        has_form = _has_contact_form(soup) or has_provider
        has_contact_link = any(("kontakt" in h or "contact" in h) for h in hrefs) or any(
            re.match(r"^(kontakt|contact)\b", a.get_text(strip=True).lower()) for a in links
        )

        findings = []
        if has_tel and not tel_clickable:
            findings.append(finding(
                "KON-01", "MITTEL", "Telefonnummer ist nicht antippbar",
                "Auf dem Handy müssen Besucher die Nummer abtippen oder kopieren, viele rufen dann gar nicht erst an.",
                solution='Die Nummer als Link einbauen: <a href="tel:+49...">, mit Landesvorwahl ohne Leerzeichen.',
            ))
        words = len(text.split())
        if not (has_tel or has_mail or has_form or has_contact_link) and words >= MIN_WORDS:
            findings.append(finding(
                "KON-02", "MITTEL", "Auf der Startseite ist kein Kontaktweg erkennbar",
                "Wer dich erreichen will, findet keinen Weg und springt ab.",
                solution="Telefon (antippbar), E-Mail oder ein Formular gut sichtbar auf der Startseite zeigen und eine Kontaktseite verlinken.",
            ))
        elif tel_clickable or has_mail or has_form:
            ways = [n for n, ok in (("Telefon", tel_clickable), ("E-Mail", has_mail), ("Formular", has_form)) if ok]
            findings.append(finding("KON-03", "POSITIV", f"Kontaktweg vorhanden ({', '.join(ways)})", "Besucher können dich direkt erreichen."))

        return {
            "has_tel": has_tel, "tel_clickable": tel_clickable, "has_mail": has_mail,
            "has_form": has_form, "has_contact_link": has_contact_link, "findings": findings,
        }
    except Exception as e:
        return {"error": str(e)}
