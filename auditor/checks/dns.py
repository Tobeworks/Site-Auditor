import re
import httpx
import dns.resolver
import dns.exception
from urllib.parse import urlparse

from auditor.findings import finding

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
        findings = []
        domain = urlparse(url).netloc.split(":")[0]
        root = domain
        if root.startswith("www."):
            root = root[4:]

        a_records = [r.to_text() for r in _query(domain, "A")]
        aaaa_records = [r.to_text() for r in _query(domain, "AAAA")]

        mx_records = []
        for r in _query(root, "MX"):
            mx_records.append({"host": str(r.exchange).rstrip("."), "priority": r.preference})

        ns_records = [str(r).rstrip(".") for r in _query(root, "NS")]
        ns_provider = None
        for r in ns_records:
            for key, name in NS_PROVIDERS.items():
                if key in r.lower():
                    ns_provider = name
                    break

        txt_records = []
        for r in _query(root, "TXT"):
            txt_records.append(r.to_text().strip('"'))

        cname = None
        try:
            cname_res = dns.resolver.resolve(domain, "CNAME")
            cname = str(list(cname_res)[0].target).rstrip(".")
        except Exception:
            pass

        ttl_a = None
        try:
            ans = dns.resolver.resolve(domain, "A")
            ttl_a = ans.rrset.ttl
        except Exception:
            pass

        spf_found = False
        spf_record = None
        for txt in txt_records:
            if txt.startswith("v=spf1"):
                spf_found = True
                spf_record = txt
                break

        dmarc_found = False
        dmarc_policy = None
        dmarc_record = None
        for r in _query(f"_dmarc.{root}", "TXT"):
            val = r.to_text().strip('"')
            if "v=DMARC1" in val:
                dmarc_found = True
                dmarc_record = val
                m = re.search(r"p=(\w+)", val)
                if m:
                    dmarc_policy = m.group(1)
                break

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

        dnssec_enabled = bool(_query(root, "DS"))

        caa_records = []
        for r in _query(root, "CAA"):
            caa_records.append(r.to_text())

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

        # DNS-01 SPF
        if not spf_found:
            findings.append(finding("DNS-01", "MITTEL", "Kein SPF-Record vorhanden",
                "Ohne SPF können Empfänger-Mailserver nicht prüfen, ob eine E-Mail über einen autorisierten Server verschickt wurde — erleichtert E-Mail-Spoofing im Namen der Domain.",
                solution='TXT-Record mit "v=spf1 ..." und den autorisierten Mailservern anlegen.'))
        else:
            findings.append(finding("DNS-01", "POSITIV", "SPF-Record vorhanden",
                "Empfänger-Server können autorisierte Absender-Server verifizieren."))

        # DNS-02 DMARC
        if not dmarc_found:
            findings.append(finding("DNS-02", "MITTEL", "Kein DMARC-Record vorhanden",
                "Ohne DMARC gibt es keine Richtlinie, wie Empfänger mit SPF/DKIM-Fehlschlägen umgehen sollen — Spoofing-Mails werden nicht konsequent abgewiesen.",
                solution='TXT-Record unter _dmarc.<domain> mit "v=DMARC1; p=quarantine;" (oder reject) anlegen.'))
        elif dmarc_policy == "none":
            findings.append(finding("DNS-02", "MITTEL", "DMARC-Policy ist 'none' (kein aktiver Schutz)",
                "Mit p=none werden DMARC-Fehlschläge nur berichtet, aber nicht blockiert oder in Quarantäne verschoben.",
                solution="Policy nach ausreichender Beobachtungszeit auf p=quarantine oder p=reject umstellen."))
        else:
            findings.append(finding("DNS-02", "POSITIV", f"DMARC aktiv (Policy: {dmarc_policy})",
                "Spoofing-Mails werden gemäß der konfigurierten Policy behandelt."))

        # DNS-03 DKIM
        if not dkim_found:
            findings.append(finding("DNS-03", "MITTEL", "Kein DKIM-Record gefunden (gängige Selektoren geprüft)",
                "Ohne DKIM können Empfänger die Integrität/Authentizität einer E-Mail nicht per Signatur prüfen.",
                solution="DKIM beim E-Mail-/Marketing-Provider aktivieren und den TXT-Record mit dem passenden Selektor veröffentlichen."))
        else:
            findings.append(finding("DNS-03", "POSITIV", f"DKIM-Record gefunden (Selektor: {dkim_selector})",
                "E-Mails können empfängerseitig per Signatur verifiziert werden."))

        # DNS-04 DNSSEC
        if not dnssec_enabled:
            findings.append(finding("DNS-04", "MITTEL", "DNSSEC nicht aktiviert",
                "Ohne DNSSEC können DNS-Antworten für diese Domain durch Cache-Poisoning/Spoofing manipuliert werden.",
                solution="DNSSEC beim DNS-Provider aktivieren (Signierung + DS-Record beim Registrar hinterlegen)."))
        else:
            findings.append(finding("DNS-04", "POSITIV", "DNSSEC aktiviert",
                "DNS-Antworten für diese Domain sind kryptographisch signiert."))

        # DNS-05 CAA
        if not caa_records:
            findings.append(finding("DNS-05", "MITTEL", "Kein CAA-Record vorhanden",
                "Ohne CAA-Einschränkung kann grundsätzlich jede öffentliche Zertifizierungsstelle ein Zertifikat für diese Domain ausstellen.",
                solution="CAA-Record anlegen, der nur die tatsächlich genutzte(n) Zertifizierungsstelle(n) autorisiert."))
        else:
            findings.append(finding("DNS-05", "POSITIV", f"CAA-Record vorhanden ({len(caa_records)} Eintrag/Einträge)",
                "Nur explizit autorisierte Zertifizierungsstellen dürfen Zertifikate für diese Domain ausstellen."))

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
            "findings": findings,
        }
    except Exception as e:
        return {"error": str(e)}
