import re
import ssl
import socket
import datetime
import httpx
from bs4 import BeautifulSoup
from urllib.parse import urlparse

from auditor.findings import finding


def _check_certificate(hostname: str) -> tuple[bool, int | None, str | None]:
    """Returns (cert_valid, days_left, expiry_date_str). days_left/expiry are None on failure."""
    try:
        ctx = ssl.create_default_context()
        with ctx.wrap_socket(socket.socket(), server_hostname=hostname) as s:
            s.settimeout(10)
            s.connect((hostname, 443))
            cert = s.getpeercert()
            not_after = cert.get("notAfter")
            if not_after:
                expiry = datetime.datetime.strptime(not_after, "%b %d %H:%M:%S %Y %Z")
                days_left = (expiry - datetime.datetime.utcnow()).days
                return days_left > 0, days_left, expiry.strftime("%Y-%m-%d")
    except Exception:
        pass
    return False, None, None


def run(url: str, html: str, soup: BeautifulSoup, headers: dict) -> dict:
    try:
        findings = []
        parsed = urlparse(url)
        hostname = parsed.netloc
        base_http = f"http://{hostname}{parsed.path or '/'}"

        # Security headers
        hsts_header = headers.get("strict-transport-security", "")
        hsts = bool(hsts_header)
        hsts_max_age = None
        hsts_include_subdomains = False
        hsts_preload = False
        if hsts_header:
            m = re.search(r"max-age=(\d+)", hsts_header)
            if m:
                hsts_max_age = int(m.group(1))
            hsts_include_subdomains = "includesubdomains" in hsts_header.lower()
            hsts_preload = "preload" in hsts_header.lower()

        csp = "content-security-policy" in headers
        x_frame_options = "x-frame-options" in headers
        x_content_type_options = headers.get("x-content-type-options", "").lower() == "nosniff"
        referrer_policy = "referrer-policy" in headers
        permissions_policy = "permissions-policy" in headers

        # HTTPS redirect + chain
        https_redirect = False
        redirect_hops = 0
        redirect_chain = []
        try:
            r = httpx.get(base_http, timeout=10, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"})
            redirect_chain = [str(h.url) for h in r.history] + [str(r.url)]
            redirect_hops = len(r.history)
            https_redirect = str(r.url).startswith("https://")
        except Exception:
            pass

        # Mixed content
        mixed_content_urls = []
        for tag in soup.find_all(["img", "script", "link", "iframe", "audio", "video", "source"]):
            for attr in ["src", "href", "action"]:
                val = tag.get(attr, "")
                if val.startswith("http://") and hostname not in val:
                    mixed_content_urls.append(val)

        cert_valid, cert_expires_in_days, cert_expiry_date = _check_certificate(hostname)

        # Cookie security flags
        raw_cookies = headers.get("set-cookie", "")
        cookies_checked = 0
        cookies_missing_secure = []
        cookies_missing_httponly = []
        cookies_missing_samesite = []

        if raw_cookies:
            cookie_lines = [raw_cookies] if "\n" not in raw_cookies else raw_cookies.splitlines()
            for line in cookie_lines:
                if "=" not in line.split(";")[0]:
                    continue
                cookie_name = line.split("=")[0].strip()
                lower = line.lower()
                cookies_checked += 1
                if "secure" not in lower:
                    cookies_missing_secure.append(cookie_name)
                if "httponly" not in lower:
                    cookies_missing_httponly.append(cookie_name)
                if "samesite" not in lower:
                    cookies_missing_samesite.append(cookie_name)

        # Subresource Integrity
        external_scripts_without_sri = []
        for tag in soup.find_all("script", src=True):
            src = tag.get("src", "")
            if src.startswith("http") and hostname not in src and not tag.get("integrity"):
                external_scripts_without_sri.append(src)
        for tag in soup.find_all("link", rel=True, href=True):
            rel = tag.get("rel", [])
            if "stylesheet" in rel:
                href = tag.get("href", "")
                if href.startswith("http") and hostname not in href and not tag.get("integrity"):
                    external_scripts_without_sri.append(href)

        # SEC-01 HTTPS-Redirect
        if not https_redirect:
            findings.append(finding("SEC-01", "HOCH", "HTTP wird nicht auf HTTPS weitergeleitet",
                "Besucher und Suchmaschinen können die unverschlüsselte HTTP-Version aufrufen — Daten sind dort im Klartext einsehbar.",
                solution="Serverseitige 301-Weiterleitung von HTTP auf HTTPS einrichten."))
        else:
            findings.append(finding("SEC-01", "POSITIV", "HTTP wird korrekt auf HTTPS weitergeleitet",
                "Besucher landen immer auf der verschlüsselten Version."))

        # SEC-02 HSTS
        if not hsts:
            findings.append(finding("SEC-02", "HOCH", "HSTS-Header fehlt",
                "Ohne HSTS kann ein Angreifer bei der ersten Verbindung einen Downgrade auf HTTP erzwingen (SSL-Stripping).",
                solution="Strict-Transport-Security-Header mit max-age=31536000; includeSubDomains; preload setzen."))
        elif hsts_max_age and hsts_max_age < 31536000:
            findings.append(finding("SEC-02", "MITTEL", f"HSTS max-age zu niedrig ({hsts_max_age}s, Minimum 31536000)",
                "Ein kurzes Schutzfenster lässt HSTS zwischen Besuchen ablaufen.",
                solution="max-age auf mindestens 31536000 (1 Jahr) erhöhen."))
        else:
            findings.append(finding("SEC-02", "POSITIV", "HSTS korrekt gesetzt" + (" (mit preload)" if hsts_preload else ""),
                "Browser erzwingen HTTPS auch bei zukünftigen Aufrufen."))

        # SEC-03 CSP
        if not csp:
            findings.append(finding("SEC-03", "HOCH", "Content-Security-Policy fehlt",
                "Ohne CSP hat der Browser keine zusätzliche Verteidigungslinie gegen XSS über eingeschleuste Fremd-Skripte.",
                solution="Content-Security-Policy-Header definieren, mindestens default-src 'self'."))
        else:
            findings.append(finding("SEC-03", "POSITIV", "Content-Security-Policy gesetzt",
                "Zusätzliche Verteidigungslinie gegen XSS ist aktiv."))

        # SEC-04 X-Frame-Options
        if not x_frame_options:
            findings.append(finding("SEC-04", "HOCH", "X-Frame-Options fehlt",
                "Die Seite kann in ein fremdes iframe eingebettet werden (Clickjacking-Risiko).",
                solution="X-Frame-Options: SAMEORIGIN oder DENY setzen (oder frame-ancestors in der CSP)."))
        else:
            findings.append(finding("SEC-04", "POSITIV", "X-Frame-Options gesetzt",
                "Einbettung in fremde iframes ist unterbunden."))

        # SEC-05 X-Content-Type-Options
        if not x_content_type_options:
            findings.append(finding("SEC-05", "MITTEL", "X-Content-Type-Options: nosniff fehlt",
                "Browser können den MIME-Type einer Ressource erraten und ausführen — Risiko bei Datei-Uploads.",
                solution="Header X-Content-Type-Options: nosniff setzen."))
        else:
            findings.append(finding("SEC-05", "POSITIV", "X-Content-Type-Options: nosniff gesetzt",
                "Browser respektieren den deklarierten MIME-Type."))

        # SEC-06 Referrer-Policy
        if not referrer_policy:
            findings.append(finding("SEC-06", "MITTEL", "Referrer-Policy fehlt",
                "Ohne explizite Policy sendet der Browser ggf. die volle URL (inkl. sensibler Query-Parameter) an Drittanbieter beim Klick auf externe Links.",
                solution="Referrer-Policy setzen, z.B. strict-origin-when-cross-origin."))
        else:
            findings.append(finding("SEC-06", "POSITIV", "Referrer-Policy gesetzt",
                "URL-Weitergabe an Drittanbieter ist eingeschränkt."))

        # SEC-07 Permissions-Policy
        if not permissions_policy:
            findings.append(finding("SEC-07", "MITTEL", "Permissions-Policy fehlt",
                "Browser-Features wie Kamera/Mikrofon/Geolocation sind nicht explizit eingeschränkt.",
                solution="Permissions-Policy setzen und nicht benötigte Features deaktivieren, z.B. camera=(), microphone=()."))
        else:
            findings.append(finding("SEC-07", "POSITIV", "Permissions-Policy gesetzt",
                "Browser-Features sind explizit eingeschränkt."))

        # SEC-08 Mixed Content
        if mixed_content_urls:
            findings.append(finding("SEC-08", "HOCH", f"Mixed Content: {len(mixed_content_urls)} HTTP-Ressource(n) auf HTTPS-Seite",
                "Browser blockieren oder warnen bei gemischten Inhalten — kann Layout brechen und wirkt unsicher.",
                solution="Alle referenzierten Ressourcen (img/script/link/iframe) auf https:// umstellen."))
        else:
            findings.append(finding("SEC-08", "POSITIV", "Keine Mixed-Content-Ressourcen gefunden",
                "Alle eingebundenen Ressourcen laufen über HTTPS."))

        # SEC-09 SSL-Zertifikat
        if cert_expires_in_days is not None:
            if cert_expires_in_days <= 0:
                findings.append(finding("SEC-09", "KRITISCH", "SSL-Zertifikat ist abgelaufen",
                    "Browser zeigen eine Sicherheitswarnung an, praktisch alle Besucher springen ab.",
                    solution="Zertifikat umgehend erneuern (z.B. automatisiertes Let's-Encrypt-Renewal einrichten)."))
            elif cert_expires_in_days < 30:
                findings.append(finding("SEC-09", "HOCH", f"SSL-Zertifikat läuft in {cert_expires_in_days} Tagen ab",
                    "Bei Ablauf ohne rechtzeitige Erneuerung ist die Seite für Besucher nicht mehr sicher erreichbar.",
                    solution="Auto-Renewal prüfen/einrichten oder Zertifikat rechtzeitig manuell erneuern."))
            else:
                findings.append(finding("SEC-09", "POSITIV", f"SSL-Zertifikat gültig (läuft ab: {cert_expiry_date})",
                    "Verschlüsselte Verbindung ist für die nächste Zeit gesichert."))

        # SEC-10 / SEC-11 Cookie-Flags
        if cookies_checked > 0:
            if cookies_missing_secure:
                findings.append(finding("SEC-10", "HOCH", f"Cookies ohne Secure-Flag: {', '.join(cookies_missing_secure)}",
                    "Diese Cookies können bei einer versehentlichen HTTP-Verbindung im Klartext übertragen werden.",
                    solution="Secure-Flag für alle Cookies setzen."))
            if cookies_missing_httponly:
                findings.append(finding("SEC-11", "HOCH", f"Cookies ohne HttpOnly-Flag: {', '.join(cookies_missing_httponly)}",
                    "Diese Cookies sind per JavaScript auslesbar — höheres Risiko bei XSS (Session-Diebstahl).",
                    solution="HttpOnly-Flag für Session-/Auth-Cookies setzen."))
            if not cookies_missing_secure and not cookies_missing_httponly:
                findings.append(finding("SEC-10", "POSITIV", "Alle geprüften Cookies haben Secure- und HttpOnly-Flag gesetzt",
                    "Cookies sind gegen Klartext-Übertragung und JS-Zugriff abgesichert."))

        # SEC-12 SRI
        if external_scripts_without_sri:
            findings.append(finding("SEC-12", "MITTEL", f"{len(external_scripts_without_sri)} externe Ressource(n) ohne Subresource Integrity",
                "Ein kompromittiertes Drittanbieter-Skript könnte unbemerkt bösartigen Code ausliefern (Supply-Chain-Risiko).",
                solution="integrity-Attribut (SRI-Hash) für alle extern eingebundenen Scripts/Stylesheets ergänzen."))
        else:
            findings.append(finding("SEC-12", "POSITIV", "Keine externen Ressourcen ohne Subresource Integrity gefunden",
                "Extern eingebundene Skripte/Styles sind gegen unbemerkte Manipulation abgesichert."))

        return {
            "https_redirect": https_redirect,
            "redirect_hops": redirect_hops,
            "redirect_chain": redirect_chain,
            "hsts": hsts,
            "hsts_max_age": hsts_max_age,
            "hsts_include_subdomains": hsts_include_subdomains,
            "hsts_preload": hsts_preload,
            "csp": csp,
            "x_frame_options": x_frame_options,
            "x_content_type_options": x_content_type_options,
            "referrer_policy": referrer_policy,
            "permissions_policy": permissions_policy,
            "mixed_content_urls": mixed_content_urls,
            "cert_valid": cert_valid,
            "cert_expires_in_days": cert_expires_in_days,
            "cert_expiry_date": cert_expiry_date,
            "cookies_checked": cookies_checked,
            "cookies_missing_secure": cookies_missing_secure,
            "cookies_missing_httponly": cookies_missing_httponly,
            "cookies_missing_samesite": cookies_missing_samesite,
            "external_scripts_without_sri": external_scripts_without_sri,
            "findings": findings,
        }
    except Exception as e:
        return {"error": str(e)}
