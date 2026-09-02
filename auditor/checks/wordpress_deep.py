import os
import re
import httpx
from bs4 import BeautifulSoup
from urllib.parse import urlparse

from auditor.findings import finding


def run(url: str, html: str, soup: BeautifulSoup, headers: dict) -> dict:
    try:
        base = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
        findings = []
        result = {
            "wp_login_exposed": False,
            "xmlrpc_exposed": False,
            "user_enumeration_possible": False,
            "exposed_users": [],
            "readme_exposed": False,
            "debug_log_exposed": False,
            "wp_version_current": None,
            "wp_version_detected": None,
            "wp_version_latest": None,
            "wpcron_exposed": False,
            "plugins_detected": [],
            "plugin_vulns": [],
            "woocommerce_detected": False,
            "woocommerce_version": None,
            "woocommerce_api_public": False,
        }

        # WP version actually installed (bug fix: this was never read before —
        # 'soup' was an unused parameter and wp_version_detected stayed None forever)
        generator = soup.find("meta", attrs={"name": "generator"}) if soup else None
        if generator:
            m = re.search(r"WordPress\s+([\d.]+)", generator.get("content", ""))
            if m:
                result["wp_version_detected"] = m.group(1)

        # collect plugins from HTML
        plugins = []
        for tag in soup.find_all(["link", "script"]):
            src = tag.get("src", "") or tag.get("href", "")
            m = re.search(r"/wp-content/plugins/([^/]+)/", src)
            if m and m.group(1) not in plugins:
                plugins.append(m.group(1))
        result["plugins_detected"] = plugins

        if "woocommerce" in html.lower():
            result["woocommerce_detected"] = True
            m = re.search(r"/wp-content/plugins/woocommerce/[^?\"']*\?ver=([\d.]+)", html)
            if m:
                result["woocommerce_version"] = m.group(1)

        with httpx.Client(timeout=8, follow_redirects=False, headers={"User-Agent": "Mozilla/5.0"}) as client:
            checks = {
                "wp_login_exposed": (f"{base}/wp-login.php", [200]),
                "xmlrpc_exposed": (f"{base}/xmlrpc.php", [200, 405]),
                "readme_exposed": (f"{base}/readme.html", [200]),
                "debug_log_exposed": (f"{base}/wp-content/debug.log", [200]),
                "wpcron_exposed": (f"{base}/wp-cron.php", [200]),
            }
            for key, (endpoint, bad_codes) in checks.items():
                try:
                    r = client.head(endpoint)
                    if r.status_code in bad_codes:
                        result[key] = True
                except Exception:
                    pass

            try:
                r = client.head(f"{base}/license.txt")
                if r.status_code == 200:
                    result["readme_exposed"] = True
            except Exception:
                pass

            try:
                r = client.get(f"{base}/wp-json/wp/v2/users", timeout=8)
                if r.status_code == 200:
                    data = r.json()
                    if isinstance(data, list) and data:
                        result["user_enumeration_possible"] = True
                        result["exposed_users"] = [u.get("slug", u.get("name", "")) for u in data[:5]]
            except Exception:
                pass

            if result["woocommerce_detected"]:
                try:
                    r = client.get(f"{base}/wp-json/wc/v3/products", timeout=8)
                    if r.status_code == 200:
                        result["woocommerce_api_public"] = True
                except Exception:
                    pass

        try:
            r = httpx.get("https://api.wordpress.org/core/version-check/1.7/", timeout=8)
            result["wp_version_latest"] = r.json()["offers"][0]["version"]
        except Exception:
            pass

        if result["wp_version_detected"] and result["wp_version_latest"]:
            result["wp_version_current"] = result["wp_version_detected"] == result["wp_version_latest"]

        api_key = os.environ.get("WPSCAN_API_KEY")
        if api_key and plugins:
            for slug in plugins[:10]:
                try:
                    r = httpx.get(
                        f"https://wpscan.com/api/v3/plugins/{slug}",
                        headers={"Authorization": f"Token token={api_key}"},
                        timeout=10,
                    )
                    if r.status_code == 200:
                        data = r.json()
                        vulns = data.get(slug, {}).get("vulnerabilities", [])
                        if vulns:
                            result["plugin_vulns"].append({"plugin": slug, "count": len(vulns), "vulns": vulns[:3]})
                except Exception:
                    pass

        # WPD-01 wp-login.php
        if result["wp_login_exposed"]:
            findings.append(finding("WPD-01", "MITTEL", "wp-login.php öffentlich erreichbar",
                "wp-login.php ist ein bekanntes Ziel für Brute-Force- und Credential-Stuffing-Angriffe.",
                solution="Zusätzlich absichern: Zwei-Faktor-Authentifizierung, Login-Rate-Limiting oder IP-Beschränkung/Umbenennung der Login-URL per Plugin."))
        else:
            findings.append(finding("WPD-01", "POSITIV", "wp-login.php nicht direkt erreichbar",
                "Kein offener Standard-Login-Endpunkt für automatisierte Angriffe."))

        # WPD-02 xmlrpc.php
        if result["xmlrpc_exposed"]:
            findings.append(finding("WPD-02", "HOCH", "xmlrpc.php erreichbar (Brute-Force-Risiko)",
                "xmlrpc.php erlaubt XML-RPC-Multicall-Requests, mit denen sich sehr viele Passwörter in einem einzigen Request testen lassen.",
                solution="xmlrpc.php deaktivieren, sofern kein Plugin/App (z.B. Jetpack, mobile App) es zwingend benötigt."))
        else:
            findings.append(finding("WPD-02", "POSITIV", "xmlrpc.php ist nicht erreichbar",
                "Kein Multicall-Angriffsvektor über XML-RPC."))

        # WPD-03 User-Enumeration
        if result["user_enumeration_possible"]:
            findings.append(finding("WPD-03", "HOCH", f"User-Enumeration möglich via REST-API ({', '.join(result['exposed_users'])})",
                "Bekannte Benutzernamen erleichtern gezielte Brute-Force- und Phishing-Angriffe erheblich.",
                solution="REST-API-Endpunkt /wp-json/wp/v2/users für anonyme Anfragen einschränken (Plugin oder Code-Snippet)."))
        else:
            findings.append(finding("WPD-03", "POSITIV", "Keine User-Enumeration über die REST-API möglich",
                "Benutzernamen sind nicht über die Standard-REST-API abgreifbar."))

        # WPD-04 readme/license Leakage
        if result["readme_exposed"]:
            findings.append(finding("WPD-04", "MITTEL", "readme.html / license.txt exponiert (Version-Leakage)",
                "Über readme.html/license.txt lässt sich oft die exakte WordPress-Version ablesen — erleichtert gezielte Exploit-Suche.",
                solution="readme.html und license.txt per Webserver-Regel blocken oder löschen."))
        else:
            findings.append(finding("WPD-04", "POSITIV", "readme.html/license.txt nicht öffentlich erreichbar",
                "Keine Versions-Leakage über diese Standarddateien."))

        # WPD-05 debug.log
        if result["debug_log_exposed"]:
            findings.append(finding("WPD-05", "KRITISCH", "debug.log öffentlich zugänglich",
                "debug.log kann Datenbank-Zugangsdaten, Pfade und Stack-Traces im Klartext enthalten.",
                solution="wp-content/debug.log per .htaccess/Webserver-Regel sperren; WP_DEBUG_LOG nur in einer nicht-öffentlichen Umgebung aktivieren."))
        else:
            findings.append(finding("WPD-05", "POSITIV", "debug.log nicht öffentlich erreichbar",
                "Keine Klartext-Fehlerprotokolle öffentlich abrufbar."))

        # WPD-06 wp-cron.php
        if result["wpcron_exposed"]:
            findings.append(finding("WPD-06", "MITTEL", "wp-cron.php direkt erreichbar",
                "Direkt aufrufbares wp-cron.php kann bei sehr häufigen Anfragen für DoS-artige Lastspitzen missbraucht werden.",
                solution="Server-seitigen Cron einrichten, DISABLE_WP_CRON setzen und den direkten Zugriff auf wp-cron.php einschränken."))
        else:
            findings.append(finding("WPD-06", "POSITIV", "wp-cron.php ist nicht direkt erreichbar",
                "Kein unnötiger externer Trigger-Endpunkt für den WP-Cron."))

        # WPD-07 Plugin-Schwachstellen
        if result["plugin_vulns"]:
            for pv in result["plugin_vulns"]:
                findings.append(finding("WPD-07", "HOCH", f"Plugin '{pv['plugin']}' hat {pv['count']} bekannte Schwachstelle(n)",
                    "Bekannte Schwachstellen in aktiven Plugins sind ein häufiger Einstiegspunkt für automatisierte Angriffs-Bots.",
                    solution=f"Plugin '{pv['plugin']}' auf die neueste Version aktualisieren oder durch eine Alternative ersetzen."))
        elif api_key and plugins:
            findings.append(finding("WPD-07", "POSITIV", "Keine bekannten Schwachstellen in den geprüften Plugins (WPScan)",
                "Aktive Plugins haben laut WPScan aktuell keine gemeldeten Schwachstellen."))

        # WPD-08 WooCommerce-API
        if result["woocommerce_detected"]:
            if result["woocommerce_api_public"]:
                findings.append(finding("WPD-08", "KRITISCH", "WooCommerce REST-API ohne Authentifizierung erreichbar",
                    "Unauthentifizierter API-Zugriff kann Produkt-/Bestelldaten offenlegen oder in schlecht konfigurierten Fällen Schreibzugriff erlauben.",
                    solution="WooCommerce-REST-API-Zugriff auf authentifizierte Requests beschränken (API-Keys erzwingen)."))
            else:
                findings.append(finding("WPD-08", "POSITIV", "WooCommerce-API ist nicht öffentlich ohne Authentifizierung erreichbar",
                    "Produkt-/Bestelldaten sind nicht anonym über die REST-API abrufbar."))

        # WPD-09 WP-Version aktuell
        if result["wp_version_current"] is False:
            findings.append(finding("WPD-09", "HOCH", f"WP-Version veraltet ({result['wp_version_detected']}, aktuell: {result['wp_version_latest']})",
                "Veraltete WordPress-Kernversionen können bekannte, öffentlich dokumentierte Sicherheitslücken enthalten.",
                solution=f"WordPress auf die neueste Version {result['wp_version_latest']} aktualisieren."))
        elif result["wp_version_current"] is True:
            findings.append(finding("WPD-09", "POSITIV", f"WordPress-Version ist aktuell ({result['wp_version_detected']})",
                "Kein Rückstand zu bekannten Sicherheitsupdates des WP-Kerns."))

        result["findings"] = findings
        return result
    except Exception as e:
        return {"error": str(e)}
