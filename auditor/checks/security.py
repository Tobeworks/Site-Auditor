import ssl
import socket
import datetime
import httpx
from bs4 import BeautifulSoup
from urllib.parse import urlparse


def run(url: str, html: str, soup: BeautifulSoup, headers: dict) -> dict:
    try:
        issues = []
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
            import re
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

        # SSL certificate
        cert_valid = False
        cert_expires_in_days = None
        cert_expiry_date = None
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
                    cert_expires_in_days = days_left
                    cert_expiry_date = expiry.strftime("%Y-%m-%d")
                    cert_valid = days_left > 0
        except Exception:
            pass

        # Cookie security flags
        raw_cookies = headers.get("set-cookie", "")
        # httpx merges set-cookie; parse individually from response if available
        cookies_checked = 0
        cookies_missing_secure = []
        cookies_missing_httponly = []
        cookies_missing_samesite = []

        # Parse set-cookie lines (may be comma-joined by httpx for simple cookies)
        if raw_cookies:
            # Split on newlines if multiple cookies joined
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

        # Build issues
        if not https_redirect:
            issues.append("HTTP wird nicht auf HTTPS weitergeleitet")
        if not hsts:
            issues.append("HSTS-Header fehlt")
        elif hsts_max_age and hsts_max_age < 31536000:
            issues.append(f"HSTS max-age zu niedrig ({hsts_max_age}s, Minimum 31536000)")
        if not csp:
            issues.append("Content-Security-Policy fehlt")
        if not x_frame_options:
            issues.append("X-Frame-Options fehlt")
        if not x_content_type_options:
            issues.append("X-Content-Type-Options: nosniff fehlt")
        if not referrer_policy:
            issues.append("Referrer-Policy fehlt")
        if not permissions_policy:
            issues.append("Permissions-Policy fehlt")
        if mixed_content_urls:
            issues.append(f"Mixed Content: {len(mixed_content_urls)} HTTP-Ressource(n) auf HTTPS-Seite")
        if cert_expires_in_days is not None:
            if cert_expires_in_days <= 0:
                issues.append("🔴 KRITISCH: SSL-Zertifikat ist abgelaufen")
            elif cert_expires_in_days < 30:
                issues.append(f"SSL-Zertifikat läuft in {cert_expires_in_days} Tagen ab")
        if cookies_missing_secure:
            issues.append(f"Cookies ohne Secure-Flag: {', '.join(cookies_missing_secure)}")
        if cookies_missing_httponly:
            issues.append(f"Cookies ohne HttpOnly-Flag: {', '.join(cookies_missing_httponly)}")
        if external_scripts_without_sri:
            issues.append(f"{len(external_scripts_without_sri)} externe Ressource(n) ohne Subresource Integrity")

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
            "issues": issues,
        }
    except Exception as e:
        return {"error": str(e)}
