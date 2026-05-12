import os
import re
import socket
import httpx
from urllib.parse import urlparse

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


def run(url: str, html: str = "", soup=None, headers: dict = None) -> dict:
    headers = headers or {}
    try:
        issues = []
        domain = urlparse(url).netloc.split(":")[0]

        # IP resolution
        try:
            ip = socket.gethostbyname(domain)
        except Exception:
            return {"error": f"Domain {domain} nicht auflösbar"}

        # IPv6
        ipv6_supported = False
        try:
            results = socket.getaddrinfo(domain, None, socket.AF_INET6)
            ipv6_supported = bool(results)
        except Exception:
            pass

        # Reverse DNS
        reverse_dns = None
        try:
            reverse_dns = socket.gethostbyaddr(ip)[0]
        except Exception:
            pass

        # ASN via ipwhois
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

        # Fallback + geolocation via ip-api.com
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

        # Identify provider
        asn_lower = (asn_name or "").lower()
        for key, name in KNOWN_PROVIDERS.items():
            if key in asn_lower:
                hosting_provider = name
                break

        # Server header
        server_header = headers.get("server")
        server_version_exposed = False
        powered_by_version_exposed = False
        if server_header:
            if re.search(r"[\d.]{3,}", server_header):
                server_version_exposed = True
                issues.append(f"Server-Version im Header sichtbar: {server_header}")
        powered_by = headers.get("x-powered-by", "")
        if powered_by and re.search(r"[\d.]{3,}", powered_by):
            powered_by_version_exposed = True
            issues.append(f"X-Powered-By mit Version sichtbar: {powered_by}")

        # Shodan
        shodan_open_ports = []
        shodan_vulns = []
        api_key = os.environ.get("SHODAN_API_KEY")
        if api_key:
            try:
                r = httpx.get(f"https://api.shodan.io/shodan/host/{ip}?key={api_key}", timeout=10)
                data = r.json()
                shodan_open_ports = data.get("ports", [])
                shodan_vulns = list(data.get("vulns", {}).keys())
                for port, service in CRITICAL_PORTS.items():
                    if port in shodan_open_ports:
                        issues.append(f"🔴 KRITISCH: Port {port} ({service}) öffentlich erreichbar (Shodan)")
            except Exception:
                pass

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
            "shodan_open_ports": shodan_open_ports,
            "shodan_vulns": shodan_vulns,
            "issues": issues,
        }
    except Exception as e:
        return {"error": str(e)}
