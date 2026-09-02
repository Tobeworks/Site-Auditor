import asyncio
from bs4 import BeautifulSoup

from auditor.findings import finding


async def _run_axe(url: str) -> dict:
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.launch(args=["--no-sandbox"])
        page = await browser.new_page()
        await page.goto(url, timeout=30000)
        await page.add_script_tag(url="https://cdnjs.cloudflare.com/ajax/libs/axe-core/4.9.1/axe.min.js")
        results = await page.evaluate("axe.run()")
        await browser.close()
        return results


def run(url: str, html: str, soup: BeautifulSoup, headers: dict) -> dict:
    try:
        findings = []

        axe_results = asyncio.run(_run_axe(url))
        raw_violations = axe_results.get("violations", [])
        incomplete = axe_results.get("incomplete", [])

        violations = []
        counts = {"critical": 0, "serious": 0, "moderate": 0, "minor": 0}
        for v in raw_violations:
            impact = v.get("impact", "minor")
            counts[impact] = counts.get(impact, 0) + 1
            wcag = next((t for t in v.get("tags", []) if t.startswith("wcag")), "")
            example_selector = ""
            if v.get("nodes"):
                example_selector = v["nodes"][0].get("target", [""])[0] if v["nodes"][0].get("target") else ""
            violations.append({
                "id": v.get("id", ""),
                "impact": impact,
                "wcag": wcag,
                "description": v.get("description", ""),
                "affected_elements": len(v.get("nodes", [])),
                "example_selector": example_selector,
            })

        images_without_alt = 0
        for img in soup.find_all("img"):
            alt = img.get("alt")
            role = img.get("role", "")
            if alt is None or (alt == "" and role != "presentation"):
                images_without_alt += 1

        unlabeled_inputs = 0
        for inp in soup.find_all(["input", "select", "textarea"]):
            if inp.get("type") == "hidden":
                continue
            inp_id = inp.get("id")
            has_label = bool(inp_id and soup.find("label", attrs={"for": inp_id}))
            has_aria = bool(inp.get("aria-label") or inp.get("aria-labelledby"))
            if not has_label and not has_aria:
                unlabeled_inputs += 1

        generic_texts = {"hier", "mehr", "click here", "read more", "weiter", "more", "details", "link"}
        generic_link_texts = []
        for a in soup.find_all("a"):
            text = a.get_text(strip=True).lower()
            if text in generic_texts:
                generic_link_texts.append(a.get_text(strip=True))

        heading_hierarchy_issues = []
        headings = [int(h.name[1]) for h in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"])]
        for i in range(1, len(headings)):
            if headings[i] - headings[i - 1] > 1:
                heading_hierarchy_issues.append(f"Sprung von H{headings[i-1]} zu H{headings[i]}")

        focus_outline_suppressed = False
        for style in soup.find_all("style"):
            text = style.get_text()
            if "outline: none" in text or "outline: 0" in text or "outline:none" in text or "outline:0" in text:
                focus_outline_suppressed = True
                break

        html_tag = soup.find("html")
        lang_attribute = html_tag.get("lang") if html_tag else None

        # A11-01 kritische WCAG-Verstöße
        if counts["critical"] > 0:
            findings.append(finding("A11-01", "KRITISCH", f"{counts['critical']} kritische Barrierefreiheits-Verstöße (WCAG)",
                "Kritische WCAG-Verstöße können bestimmte Nutzergruppen (z.B. Screenreader-Nutzer) komplett von der Nutzung ausschließen.",
                solution="Kritische axe-core-Verstöße vorrangig beheben, siehe Detail-Report je Regel-ID."))
        else:
            findings.append(finding("A11-01", "POSITIV", "Keine kritischen WCAG-Verstöße gefunden",
                "Kein Ausschluss von Nutzergruppen durch kritische Barrieren erkannt."))

        # A11-02 schwerwiegende WCAG-Verstöße
        if counts["serious"] > 0:
            findings.append(finding("A11-02", "HOCH", f"{counts['serious']} schwerwiegende Barrierefreiheits-Verstöße",
                "Schwerwiegende Verstöße erschweren die Nutzung für Menschen mit Behinderung erheblich, ohne sie komplett auszuschließen.",
                solution="Schwerwiegende axe-core-Verstöße beheben, siehe Detail-Report je Regel-ID."))
        else:
            findings.append(finding("A11-02", "POSITIV", "Keine schwerwiegenden WCAG-Verstöße gefunden",
                "Kein erheblicher Nutzungsnachteil durch schwerwiegende Barrieren erkannt."))

        # A11-03 Bilder ohne Alt-Text
        if images_without_alt > 0:
            findings.append(finding("A11-03", "MITTEL", f"{images_without_alt} Bild(er) ohne Alt-Text",
                "Screenreader können den Bildinhalt nicht wiedergeben — für blinde/sehbehinderte Nutzer nicht zugänglich.",
                solution='alt-Attribut für jedes Bild ergänzen (leer alt="" nur bei rein dekorativen Bildern).'))
        else:
            findings.append(finding("A11-03", "POSITIV", "Alle Bilder haben ein Alt-Attribut",
                "Bildinhalte sind für Screenreader zugänglich."))

        # A11-04 Formularfelder ohne Label
        if unlabeled_inputs > 0:
            findings.append(finding("A11-04", "MITTEL", f"{unlabeled_inputs} Formularfeld(er) ohne Label",
                "Ohne Label wissen Screenreader-Nutzer nicht, wofür ein Eingabefeld gedacht ist.",
                solution="<label for=\"...\">, aria-label oder aria-labelledby für jedes Formularfeld ergänzen."))
        else:
            findings.append(finding("A11-04", "POSITIV", "Alle Formularfelder sind beschriftet",
                "Formularfelder sind für Screenreader eindeutig zuordenbar."))

        # A11-05 generische Linktexte
        if generic_link_texts:
            findings.append(finding("A11-05", "MITTEL", f"Generische Linktexte gefunden: {', '.join(set(generic_link_texts))}",
                "Generische Linktexte wie 'hier klicken' geben Screenreader-Nutzern, die eine Linkliste durchgehen, keinen Kontext.",
                solution="Linktexte so formulieren, dass sie auch isoliert (ohne umgebenden Text) verständlich sind."))
        else:
            findings.append(finding("A11-05", "POSITIV", "Keine generischen Linktexte gefunden",
                "Linktexte sind auch außerhalb ihres Kontexts verständlich."))

        # A11-06 Überschriften-Hierarchie
        if heading_hierarchy_issues:
            findings.append(finding("A11-06", "MITTEL", f"Überschriften-Hierarchie-Probleme: {'; '.join(heading_hierarchy_issues[:3])}",
                "Übersprungene Überschriften-Ebenen erschweren Screenreader-Nutzern die Orientierung in der Seitenstruktur.",
                solution="Überschriften-Ebenen ohne Sprünge verwenden (z.B. nicht direkt von H1 zu H3)."))
        else:
            findings.append(finding("A11-06", "POSITIV", "Überschriften-Hierarchie ist konsistent",
                "Klare, sprungfreie Seitenstruktur für Screenreader-Nutzer."))

        # A11-07 Focus-Outline
        if focus_outline_suppressed:
            findings.append(finding("A11-07", "MITTEL", "Focus-Outline unterdrückt (outline:none/0 in CSS)",
                "Tastatur-Nutzer sehen nicht mehr, welches Element gerade fokussiert ist.",
                solution="outline nicht komplett entfernen, sondern durch einen sichtbaren, kontraststarken Fokus-Stil ersetzen."))
        else:
            findings.append(finding("A11-07", "POSITIV", "Focus-Outline ist nicht unterdrückt",
                "Tastatur-Nutzer können den aktuellen Fokus erkennen."))

        # A11-08 HTML lang-Attribut
        if not lang_attribute:
            findings.append(finding("A11-08", "MITTEL", "HTML lang-Attribut fehlt",
                "Ohne lang-Attribut wählen Screenreader ggf. die falsche Sprachausgabe/Aussprache.",
                solution="lang-Attribut am <html>-Tag setzen, z.B. lang=\"de\"."))
        else:
            findings.append(finding("A11-08", "POSITIV", f"HTML lang-Attribut gesetzt ({lang_attribute})",
                "Screenreader wählen die korrekte Sprachausgabe."))

        return {
            "violations": violations,
            "incomplete": [{"id": v.get("id"), "description": v.get("description")} for v in incomplete[:10]],
            "violations_count": counts,
            "manual_checks": {
                "images_without_alt": images_without_alt,
                "unlabeled_inputs": unlabeled_inputs,
                "generic_link_texts": list(set(generic_link_texts)),
                "heading_hierarchy_issues": heading_hierarchy_issues,
                "focus_outline_suppressed": focus_outline_suppressed,
                "lang_attribute": lang_attribute,
            },
            "findings": findings,
        }
    except Exception as e:
        return {"error": str(e)}
