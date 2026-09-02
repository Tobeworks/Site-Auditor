import re
import httpx
from bs4 import BeautifulSoup
from urllib.parse import urlparse

from auditor.findings import finding

KNOWN_THIRD_PARTY_CATEGORIES = {
    "google-analytics.com": "Analytics",
    "googletagmanager.com": "Analytics",
    "analytics.google.com": "Analytics",
    "facebook.net": "Social/Ads",
    "connect.facebook.net": "Social/Ads",
    "fonts.googleapis.com": "Fonts",
    "fonts.gstatic.com": "Fonts",
    "ajax.googleapis.com": "CDN",
    "cdnjs.cloudflare.com": "CDN",
    "cdn.jsdelivr.net": "CDN",
    "plausible.io": "Analytics",
    "hotjar.com": "Analytics",
    "clarity.ms": "Analytics",
    "doubleclick.net": "Ads",
    "googlesyndication.com": "Ads",
    "youtube.com": "Media",
    "youtu.be": "Media",
    "vimeo.com": "Media",
    "twitter.com": "Social",
    "platform.twitter.com": "Social",
    "instagram.com": "Social",
}

COOKIE_SOLUTIONS = [
    "cookiebot", "cookieconsent", "cookie-banner", "cmplz",
    "borlabs-cookie", "usercentrics", "onetrust", "didomi",
]

CONSENT_REQUIRED_PATTERNS = {
    "gtag(": "Google Analytics/GTM",
    "ga(": "Google Analytics",
    "fbq(": "Facebook Pixel",
    "hotjar": "Hotjar",
    "_clarity": "Microsoft Clarity",
}

COOKIELESS_PATTERNS = {
    "plausible": "Plausible (cookielos, kein Consent nötig)",
}


def _detect_matomo(html: str, hostname: str) -> dict:
    if "_paq" not in html:
        return {"found": False}

    cookieless = False
    external = False
    matomo_url = None

    if "disableCookies" in html or "requireCookieConsent" in html or "cookieless" in html.lower():
        cookieless = True

    m = re.search(r'["\']([^"\']*matomo[^"\']*\.php)["\']', html, re.IGNORECASE)
    if not m:
        m = re.search(r'setTrackerUrl\(["\']([^"\']+)["\']', html)
    if m:
        matomo_url = m.group(1)
        parsed = urlparse(matomo_url if matomo_url.startswith("http") else f"https:{matomo_url}")
        tracker_host = parsed.netloc
        if tracker_host and tracker_host != hostname:
            external = True

    return {
        "found": True,
        "cookieless": cookieless,
        "external": external,
        "matomo_url": matomo_url,
    }


def run(url: str, html: str, soup: BeautifulSoup, headers: dict) -> dict:
    try:
        findings = []
        hostname = urlparse(url).netloc
        base = f"{urlparse(url).scheme}://{hostname}"

        def find_link(texts, paths):
            for a in soup.find_all("a", href=True):
                link_text = a.get_text(strip=True).lower()
                if any(t.lower() in link_text for t in texts):
                    return a.get("href", "")
            with httpx.Client(timeout=5, headers={"User-Agent": "Mozilla/5.0"}) as client:
                for path in paths:
                    try:
                        r = client.head(f"{base}{path}")
                        if r.status_code in (200, 301, 302):
                            return path
                    except Exception:
                        pass
            return None

        impressum_url = find_link(
            ["impressum", "imprint", "legal notice"],
            ["/impressum", "/imprint", "/legal-notice"],
        )
        privacy_url = find_link(
            ["datenschutz", "datenschutzerklärung", "privacy policy", "privacy"],
            ["/datenschutz", "/privacy-policy", "/privacy"],
        )

        html_lower = html.lower()
        cookie_banner_detected = False
        cookie_solution = None
        for solution in COOKIE_SOLUTIONS:
            if solution in html_lower:
                cookie_banner_detected = True
                cookie_solution = solution
                break

        matomo = _detect_matomo(html, hostname)
        matomo_needs_consent = False
        matomo_note = None
        if matomo["found"]:
            if matomo["cookieless"]:
                matomo_note = "Matomo (cookielos konfiguriert – kein Consent erforderlich)"
            elif not matomo["external"]:
                matomo_note = "Matomo (selbst-gehostet – bei cookielos-Betrieb kein Consent nötig, bitte prüfen)"
                matomo_needs_consent = True
            else:
                matomo_note = f"Matomo Cloud/extern ({matomo['matomo_url']}) – Consent erforderlich"
                matomo_needs_consent = True

        tracking_needs_consent = []
        for pattern, label in CONSENT_REQUIRED_PATTERNS.items():
            if pattern in html:
                tracking_needs_consent.append(label)

        tracking_cookieless = []
        for pattern, label in COOKIELESS_PATTERNS.items():
            if pattern in html:
                tracking_cookieless.append(label)

        tracking_in_html = tracking_needs_consent + ([matomo_note] if matomo["found"] else []) + tracking_cookieless

        third_party_domains = []
        seen = set()
        for tag in soup.find_all(["script", "link", "img", "iframe"]):
            for attr in ["src", "href"]:
                val = tag.get(attr, "")
                if not val or not val.startswith("http"):
                    continue
                domain = urlparse(val).netloc
                if domain and domain != hostname and domain not in seen:
                    seen.add(domain)
                    category = "Sonstiges"
                    for key, cat in KNOWN_THIRD_PARTY_CATEGORIES.items():
                        if key in domain:
                            category = cat
                            break
                    third_party_domains.append({"domain": domain, "category": category})

        # LGL-01 Impressum
        if not impressum_url:
            findings.append(finding("LGL-01", "HOCH", "Kein Impressum gefunden",
                "In Deutschland ist ein Impressum nach § 5 TMG/DDG für geschäftsmäßige Websites verpflichtend — fehlt es, drohen Abmahnungen.",
                solution="Impressum-Seite mit den gesetzlich vorgeschriebenen Pflichtangaben erstellen und verlinken."))
        else:
            findings.append(finding("LGL-01", "POSITIV", f"Impressum gefunden ({impressum_url})",
                "Pflichtangaben sind erreichbar."))

        # LGL-02 Datenschutzerklärung
        if not privacy_url:
            findings.append(finding("LGL-02", "HOCH", "Keine Datenschutzerklärung gefunden",
                "Eine Datenschutzerklärung ist nach Art. 13 DSGVO verpflichtend, sobald personenbezogene Daten verarbeitet werden (z.B. durch Tracking, Kontaktformulare).",
                solution="Datenschutzerklärung erstellen und von jeder Seite aus verlinken."))
        else:
            findings.append(finding("LGL-02", "POSITIV", f"Datenschutzerklärung gefunden ({privacy_url})",
                "Nutzer können sich über die Datenverarbeitung informieren."))

        # LGL-03 Consent-pflichtiges Tracking
        needs_consent = tracking_needs_consent + (["Matomo"] if matomo_needs_consent else [])
        if needs_consent and not cookie_banner_detected:
            findings.append(finding("LGL-03", "HOCH", f"Consent-pflichtiges Tracking ohne Cookie-Banner: {', '.join(needs_consent)}",
                "Tracking ohne vorherige Einwilligung verstößt gegen die TTDSG-/DSGVO-Vorgaben zur Cookie-Einwilligung.",
                solution="Cookie-Consent-Lösung einbinden, die Tracking-Skripte erst nach Zustimmung lädt."))
        elif needs_consent:
            findings.append(finding("LGL-03", "MITTEL", f"Consent-pflichtiges Tracking aktiv: {', '.join(needs_consent)} – DSGVO-Prüfung empfohlen",
                "Ein Cookie-Banner ist vorhanden, es lässt sich von außen aber nicht sicher prüfen, ob das Tracking tatsächlich erst nach Zustimmung geladen wird.",
                solution="Prüfen, ob die Tracking-Skripte technisch erst nach erteilter Einwilligung geladen werden (nicht nur der Banner angezeigt wird)."))
        else:
            findings.append(finding("LGL-03", "POSITIV", "Kein zwingend consent-pflichtiges Tracking erkannt",
                "Kein bekanntes Tracking-Skript gefunden, das eine vorherige Einwilligung erfordert."))

        return {
            "impressum_found": bool(impressum_url),
            "impressum_url": impressum_url,
            "privacy_found": bool(privacy_url),
            "privacy_url": privacy_url,
            "cookie_banner_detected": cookie_banner_detected,
            "cookie_solution": cookie_solution,
            "tracking_needs_consent": tracking_needs_consent,
            "tracking_cookieless": tracking_cookieless,
            "matomo": matomo if matomo["found"] else None,
            "matomo_note": matomo_note,
            "tracking_in_html": tracking_in_html,
            "third_party_domains": third_party_domains,
            "findings": findings,
        }
    except Exception as e:
        return {"error": str(e)}
