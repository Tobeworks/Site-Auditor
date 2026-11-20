"""Handy-Bedienbarkeit: Viewport-Meta (aus dem HTML) und Signale des ersten Handy-Bildschirms (aus first_view, Chromium 390 px).
Ohne Browserdaten läuft nur die Viewport-Prüfung."""
from bs4 import BeautifulSoup

from auditor.findings import finding

SMALL_TARGETS_MIN = 3  # so viele zu kleine Tippflächen und der Anteil unten, dann ein Befund
SMALL_TARGETS_SHARE = 0.3


def run(url: str, html: str, soup: BeautifulSoup, headers: dict, first_view: dict | None = None) -> dict:
    try:
        findings = []
        meta = soup.find("meta", attrs={"name": "viewport"})
        content = ((meta.get("content") if meta else "") or "").replace(" ", "").lower()
        if "width=device-width" not in content:
            findings.append(finding(
                "UXF-01", "HOCH", "Kein Viewport-Meta für Handys gesetzt",
                "Ohne Viewport-Angabe zeigt das Handy die Seite als verkleinerte Desktop-Ansicht. Besucher müssen zoomen, viele springen ab, und Google wertet die Seite als nicht mobiltauglich.",
                solution='Im <head> ergänzen: <meta name="viewport" content="width=device-width, initial-scale=1">.',
            ))
        else:
            findings.append(finding("UXF-01", "POSITIV", "Viewport-Meta für Handys gesetzt", "Die Seite passt sich der Bildschirmbreite an."))

        mobile = (first_view or {}).get("mobile")
        if isinstance(mobile, dict) and (first_view or {}).get("status") in ("ok", "empty"):
            if mobile.get("overflowX"):
                findings.append(finding(
                    "UXF-02", "HOCH", "Die Seite scrollt auf dem Handy seitlich",
                    f"Inhalt ragt über die Bildschirmbreite hinaus ({mobile.get('scrollWidth')} statt {mobile.get('width')} Pixel). Das wirkt kaputt und erschwert das Lesen und Tippen.",
                    solution="Das Element suchen, das breiter als der Bildschirm ist (feste Breiten, Tabellen, Bilder ohne max-width) und es flexibel machen.",
                ))
            else:
                findings.append(finding("UXF-02", "POSITIV", "Kein seitliches Scrollen auf dem Handy", "Der Inhalt passt in die Bildschirmbreite."))

            if first_view.get("status") == "ok":  # bei "empty" verdeckt ein Overlay den Bildschirm, das sagt nichts über die Seite
                if not mobile.get("cta"):
                    findings.append(finding(
                        "UXF-03", "MITTEL", "Im ersten Handy-Bildschirm gibt es keinen Weg zu handeln",
                        "Wer ankommt, sieht weder Anruf, Mail, Formular noch einen Button zu Anfrage oder Termin und muss erst suchen. Viele suchen nicht.",
                        solution="Im ersten Bildschirm einen klaren Button (Anfrage, Termin, Anruf) oder eine antippbare Telefonnummer zeigen.",
                    ))
                else:
                    findings.append(finding("UXF-03", "POSITIV", "Im ersten Handy-Bildschirm gibt es einen Weg zu handeln", "Besucher sehen sofort, was sie als Nächstes tun können."))

            targets, small = int(mobile.get("targets") or 0), int(mobile.get("small") or 0)
            if small >= SMALL_TARGETS_MIN and targets and small / targets >= SMALL_TARGETS_SHARE:
                findings.append(finding(
                    "UXF-04", "MITTEL", f"{small} von {targets} Tippflächen im ersten Bildschirm sind zu klein",
                    "Buttons und Links unter 24 mal 24 Pixel trifft man mit dem Daumen schwer. Das ist auch ein Verstoß gegen WCAG 2.2 (Erfolgskriterium 2.5.8).",
                    solution="Tippflächen auf mindestens 24, besser 44 Pixel vergrößern (Padding statt kleinerer Schrift).",
                ))

        return {"browser": isinstance(mobile, dict), "mobile": mobile, "findings": findings}
    except Exception as e:
        return {"error": str(e)}
