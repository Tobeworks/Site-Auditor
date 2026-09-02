import os
import re
import socket
import datetime
import httpx
from urllib.parse import urlparse

from auditor.findings import finding
from auditor.checks._eol_dates import PHP_EOL_DATES

KNOWN_PROVIDERS = {
    "hetzner": "Hetzner",
    "netcup": "Netcup",
    "ionos": "IONOS",
    "strato": "Strato",
    "ovh": "OVH",
    "amazon": "AWS",
    "cloudflare": "Cloudflare",
    "digitalocean": "DigitalOcean",
    "contabo": "Contabo",
    "linode": "Linode",
    "vultr": "Vultr",
}

CRITICAL_PORTS = {3306: "MySQL", 5432: "PostgreSQL", 6379: "Redis", 27017: "MongoDB", 9200: "Elasticsearch"}


def _php_eol_check(powered_by: str) -> tuple[str | None, str | None]:
    """Returns (php_version, eol_date_str) if a known PHP version was detected."""
    m = re.search(r"PHP/([\d.]+)", powered_by)
    if not m:
        return None, None
    version = m.group(1)
    parts = version.split(".")
    if len(parts) < 2:
        return version, None
    minor = f"{parts[0]}.{parts[1]}"
    return version, PHP_EOL_DATES.get(minor)


def run(url: str, html: str = "", soup=None, headers: dict = None) -> dict:
    headers = headers or {}
    try:
        findings = []
        domain = urlparse(url).netloc.split(":")[0]

        try:
            ip = socket.gethostbyname(domain)
        except Exception:
            return {"error": f"Domain {domain} nicht auflösbar"}

        ipv6_supported = False
        try:
            results = socket.getaddrinfo(domain, None, socket.AF_INET6)
            ipv6_supported = bool(results)
        except Exception:
            pass

        reverse_dns = None
        try:
            reverse_dns = socket.gethostbyaddr(ip)[0]
        except Exception:
            pass

        asn = asn_name = network_cidr = None
        try:
            from ipwhois import IPWhois
            obj = IPWhois(ip)
            result = obj.lookup_rdap(asn_methods=["dns", "whois", "http"])
            asn = result.get("asn")
            asn_name = result.get("asn_description", "")
            network_cidr = result.get("network", {}).get("cidr")
        except Exception:
            pass

        country = city = timezone = hosting_provider = None
        try:
            r = httpx.get(f"http://ip-api.com/json/{ip}?fields=country,city,timezone,org,as", timeout=8)
            data = r.json()
            country = data.get("country")
            city = data.get("city")
            timezone = data.get("timezone")
            if not asn_name:
                asn_name = data.get("org", "")
        except Exception:
            pass

        asn_lower = (asn_name or "").lower()
        for key, name in KNOWN_PROVIDERS.items():
            if key in asn_lower:
                hosting_provider = name
                break

        server_header = headers.get("server")
        server_version_exposed = False
        powered_by_version_exposed = False
        if server_header and re.search(r"[\d.]{3,}", server_header):
            server_version_exposed = True

        powered_by = headers.get("x-powered-by", "")
        if powered_by and re.search(r"[\d.]{3,}", powered_by):
            powered_by_version_exposed = True

        shodan_open_ports = []
        shodan_vulns = []
        shodan_checked = False
        api_key = os.environ.get("SHODAN_API_KEY")
        if api_key:
            shodan_checked = True
            try:
                r = httpx.get(f"https://api.shodan.io/shodan/host/{ip}?key={api_key}", timeout=10)
                data = r.json()
                shodan_open_ports = data.get("ports", [])
                shodan_vulns = list(data.get("vulns", {}).keys())
            except Exception:
                pass

        # HST-01 Server-Header-Version
        if server_version_exposed:
            findings.append(finding("HST-01", "MITTEL", f"Server-Version im Header sichtbar: {server_header}",
                "Eine sichtbare Server-Version erleichtert Angreifern das gezielte Suchen nach bekannten Schwachstellen dieser Version.",
                solution="Server-Header minimieren (z.B. server_tokens off; bei Nginx, ServerTokens Prod bei Apache)."))
        else:
            findings.append(finding("HST-01", "POSITIV", "Server-Header zeigt keine Versionsnummer",
                "Erschwert automatisiertes Fingerprinting der Server-Software."))

        # HST-02 X-Powered-By-Version
        if powered_by_version_exposed:
            findings.append(finding("HST-02", "MITTEL", f"X-Powered-By mit Version sichtbar: {powered_by}",
                "Eine sichtbare Framework-/Sprachversion erleichtert Angreifern das gezielte Suchen nach bekannten Schwachstellen.",
                solution="X-Powered-By-Header serverseitig deaktivieren (z.B. expose_php = Off in php.ini)."))
        else:
            findings.append(finding("HST-02", "POSITIV", "Kein Versions-Leak über X-Powered-By",
                "Erschwert automatisiertes Fingerprinting des Backends."))

        # HST-03 Shodan kritische Ports
        if shodan_checked:
            critical_open = [(p, s) for p, s in CRITICAL_PORTS.items() if p in shodan_open_ports]
            if critical_open:
                for port, service in critical_open:
                    findings.append(finding("HST-03", "KRITISCH", f"Port {port} ({service}) öffentlich erreichbar (Shodan)",
                        "Ein öffentlich erreichbarer Datenbank-/Cache-Port ist ein direktes Einfallstor, falls kein starkes Passwort/keine Firewall-Regel greift.",
                        solution=f"Port {port} per Firewall auf interne/VPN-Zugriffe beschränken, nicht öffentlich exponieren."))
            else:
                findings.append(finding("HST-03", "POSITIV", "Keine kritischen Ports öffentlich erreichbar (Shodan)",
                    "Keine bekannten Datenbank-/Cache-Ports sind von außen erreichbar."))

        # HST-04 PHP-Version EOL-Abgleich
        php_version, eol_date_str = _php_eol_check(powered_by)
        if php_version and eol_date_str:
            eol_date = datetime.date.fromisoformat(eol_date_str)
            today = datetime.date.today()
            days_left = (eol_date - today).days
            if days_left < 0:
                findings.append(finding("HST-04", "KRITISCH", f"PHP {php_version} ist seit {eol_date_str} End-of-Life (keine Security-Updates mehr)",
                    "Bekannt gewordene Sicherheitslücken in einer EOL-PHP-Version werden nicht mehr gepatcht — bei Verarbeitung personenbezogener Daten relevant für die technisch-organisatorischen Maßnahmen nach Art. 32 DSGVO (kein Rechtsrat, nur ein fachlicher Hinweis).",
                    solution="Auf eine aktuell unterstützte PHP-Version aktualisieren (siehe php.net/supported-versions.php)."))
            elif days_left < 183:
                findings.append(finding("HST-04", "MITTEL", f"PHP {php_version} erreicht End-of-Life am {eol_date_str} (in {days_left} Tagen)",
                    "Nach dem EOL-Datum erhält diese PHP-Version keine Sicherheitsupdates mehr.",
                    solution="Migration auf eine neuere PHP-Version rechtzeitig vor dem EOL-Datum einplanen."))
            else:
                findings.append(finding("HST-04", "POSITIV", f"PHP {php_version} wird noch bis {eol_date_str} unterstützt",
                    "Sicherheitsupdates für die eingesetzte PHP-Version sind aktuell noch verfügbar."))

        return {
            "ip": ip,
            "ipv6_supported": ipv6_supported,
            "reverse_dns": reverse_dns,
            "asn": asn,
            "asn_name": asn_name,
            "hosting_provider": hosting_provider,
            "network_cidr": network_cidr,
            "country": country,
            "city": city,
            "timezone": timezone,
            "server_header": server_header,
            "server_version_exposed": server_version_exposed,
            "powered_by_version_exposed": powered_by_version_exposed,
            "php_version": php_version,
            "php_eol_date": eol_date_str,
            "shodan_open_ports": shodan_open_ports,
            "shodan_vulns": shodan_vulns,
            "findings": findings,
        }
    except Exception as e:
        return {"error": str(e)}
