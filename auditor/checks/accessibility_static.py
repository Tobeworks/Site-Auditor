from bs4 import BeautifulSoup

from auditor.findings import finding, severity_by_share

SKIP_INPUT_TYPES = {"hidden", "submit", "button", "image", "reset"}


def _is_labeled(field, label_targets: set[str]) -> bool:
    if field.get("aria-label") or field.get("aria-labelledby") or field.get("title"):
        return True
    if field.get("id") and field["id"] in label_targets:
        return True
    return field.find_parent("label") is not None


def run(url: str, html: str, soup: BeautifulSoup, headers: dict) -> dict:
    """Barrierefreiheit ohne Browser: Sprache, Alt-Texte, Beschriftungen, Erklärung. Schnelltest, kein
    Ersatz für den vollen Test (Modul a11y). ponytail: prüft nur das Markup, keine Kontraste."""
    try:
        findings = []
        html_tag = soup.find("html")
        lang = (html_tag.get("lang") or "").strip() or None if html_tag else None
        if not lang:
            findings.append(finding(
                "BAR-01", "MITTEL", "Keine Sprache der Seite angegeben",
                "Screenreader wissen nicht, in welcher Sprache sie vorlesen sollen, und lesen Deutsch dann oft mit englischer Aussprache.",
                solution='Im <html>-Tag die Sprache setzen, zum Beispiel <html lang="de">.',
            ))

        images = soup.find_all("img")
        # alt="" ist erlaubt (dekoratives Bild), es fehlt nur das Attribut selbst.
        without_alt = [i for i in images if i.get("alt") is None]
        if without_alt:
            findings.append(finding(
                "BAR-02", severity_by_share(len(without_alt), len(images)), f"{len(without_alt)} von {len(images)} Bildern ohne Alt-Text",
                "Menschen mit Screenreader erfahren nicht, was auf den Bildern zu sehen ist. Auch Google versteht die Bilder schlechter.",
                solution='Jedem inhaltlichen Bild einen kurzen alt-Text geben, rein dekorative Bilder mit alt="" markieren.',
            ))

        label_targets = {l["for"] for l in soup.find_all("label", attrs={"for": True})}
        fields = [f for f in soup.find_all(["input", "select", "textarea"])
                  if (f.get("type") or "text").lower() not in SKIP_INPUT_TYPES]
        unlabeled = [f for f in fields if not _is_labeled(f, label_targets)]
        if unlabeled:
            findings.append(finding(
                "BAR-03", severity_by_share(len(unlabeled), len(fields)), f"{len(unlabeled)} Formularfelder ohne Beschriftung",
                "Screenreader können nicht sagen, was in das Feld gehört. Ein Platzhalter allein zählt nicht als Beschriftung.",
                solution="Jedes Feld mit einem <label for=...> oder aria-label versehen.",
            ))

        statement = any(
            "barrierefreiheit" in (a.get("href", "") + " " + a.get_text()).lower() for a in soup.find_all("a")
        )
        if statement:
            findings.append(finding(
                "BAR-04", "POSITIV", "Link zur Barrierefreiheitserklärung gefunden",
                "Wer die Seite nutzt, findet Angaben zur Barrierefreiheit.",
            ))

        return {
            "lang": lang, "images_total": len(images), "images_without_alt": len(without_alt),
            "unlabeled_fields": len(unlabeled), "accessibility_statement": statement, "findings": findings,
        }
    except Exception as e:
        return {"error": str(e)}
