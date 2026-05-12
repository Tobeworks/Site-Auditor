import httpx
import dns.resolver
import dns.exception
from urllib.parse import urlparse

NS_PROVIDERS = {
    "cloudflare": "Cloudflare",
    "awsdns": "AWS Route53",
    "ionos": "IONOS",
    "hetzner": "Hetzner",
    "dnsimple": "DNSimple",
    "ovh": "OVH",
}

DKIM_SELECTORS = ["default", "google", "mail", "dkim", "k1", "selector1", "selector2"]


def _query(domain, rtype):
    try:
        return dns.resolver.resolve(domain, rtype)
    except Exception:
        return []


def run(url: str, html: str = "", soup=None, headers: dict = None) -> dict:
    headers = headers or {}
    try:
        issues = []
        domain = urlparse(url).netloc.split(":")[0]
        # Strip www
        root = domain
        if root.startswith("www."):
            root = root[4:]

        # A / AAAA
        a_records = [r.to_text() for r in _query(domain, "A")]
        aaaa_records = [r.to_text() for r in _query(domain, "AAAA")]

        # MX
        mx_records = []
        for r in _query(root, "MX"):
            mx_records.append({"host": str(r.exchange).rstrip("."), "priority": r.preference})

        # NS
        ns_records = [str(r).rstrip(".") for r in _query(root, "NS")]
        ns_provider = None
        for r in ns_records:
            for key, name in NS_PROVIDERS.items():
                if key in r.lower():
                    ns_provider = name
                    break

        # TXT
        txt_records = []
        for r in _query(root, "TXT"):
            txt_records.append(r.to_text().strip('"'))

        # CNAME
        cname = None
        try:
            cname_res = dns.resolver.resolve(domain, "CNAME")
            cname = str(list(cname_res)[0].target).rstrip(".")
        except Exception:
            pass

        # TTL
        ttl_a = None
        try:
            ans = dns.resolver.resolve(domain, "A")
            ttl_a = ans.rrset.ttl
        except Exception:
            pass

        # SPF
        spf_found = False
        spf_record = None
        for txt in txt_records:
            if txt.startswith("v=spf1"):
                spf_found = True
                spf_record = txt
                break

        # DMARC
        dmarc_found = False
        dmarc_policy = None
        dmarc_record = None
        import re
        for r in _query(f"_dmarc.{root}", "TXT"):
            val = r.to_text().strip('"')
            if "v=DMARC1" in val:
                dmarc_found = True
                dmarc_record = val
                m = re.search(r"p=(\w+)", val)
                if m:
                    dmarc_policy = m.group(1)
                break

        # DKIM
        dkim_found = False
        dkim_selector = None
        for selector in DKIM_SELECTORS:
            for r in _query(f"{selector}._domainkey.{root}", "TXT"):
                val = r.to_text()
                if "v=DKIM1" in val or "p=" in val:
                    dkim_found = True
                    dkim_selector = selector
                    break
            if dkim_found:
                break

        # DNSSEC
        dnssec_enabled = bool(_query(root, "DS"))

        # CAA
        caa_records = []
        for r in _query(root, "CAA"):
            caa_records.append(r.to_text())

        # BIMI
        bimi_found = False
        bimi_logo_url = None
        for r in _query(f"default._bimi.{root}", "TXT"):
            val = r.to_text().strip('"')
            if "v=BIMI1" in val:
                bimi_found = True
                m = re.search(r"l=([^\s;]+)", val)
                if m:
                    bimi_logo_url = m.group(1)
                break

        # MTA-STS
        mta_sts_found = False
        for r in _query(f"_mta-sts.{root}", "TXT"):
            if "v=STSv1" in r.to_text():
                mta_sts_found = True
                break
        if not mta_sts_found:
            try:
                r = httpx.head(f"https://mta-sts.{root}/.well-known/mta-sts.txt", timeout=5)
                mta_sts_found = r.status_code == 200
            except Exception:
                pass

        # Issues
        if not spf_found:
            issues.append("Kein SPF-Record vorhanden")
        if not dmarc_found:
            issues.append("Kein DMARC-Record vorhanden")
        elif dmarc_policy == "none":
            issues.append("DMARC-Policy ist 'none' (kein aktiver Schutz)")
        if not dkim_found:
            issues.append("Kein DKIM-Record gefunden (gängige Selektoren geprüft)")
        if not dnssec_enabled:
            issues.append("DNSSEC nicht aktiviert")
        if not caa_records:
            issues.append("Kein CAA-Record vorhanden (beliebige CAs können Zertifikate ausstellen)")

        return {
            "a_records": a_records,
            "aaaa_records": aaaa_records,
            "mx_records": mx_records,
            "ns_records": ns_records,
            "ns_provider": ns_provider,
            "txt_records": txt_records,
            "cname": cname,
            "ttl_a": ttl_a,
            "spf_found": spf_found,
            "spf_record": spf_record,
            "dmarc_found": dmarc_found,
            "dmarc_policy": dmarc_policy,
            "dmarc_record": dmarc_record,
            "dkim_found": dkim_found,
            "dkim_selector": dkim_selector,
            "dnssec_enabled": dnssec_enabled,
            "caa_records": caa_records,
            "bimi_found": bimi_found,
            "bimi_logo_url": bimi_logo_url,
            "mta_sts_found": mta_sts_found,
            "issues": issues,
        }
    except Exception as e:
        return {"error": str(e)}
