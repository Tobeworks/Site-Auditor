import os
import httpx
from bs4 import BeautifulSoup
from urllib.parse import urlparse


def run(url: str, html: str, soup: BeautifulSoup, headers: dict) -> dict:
    try:
        base = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
        issues = []
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
            "issues": [],
        }

        import re
        # collect plugins from HTML
        plugins = []
        for tag in soup.find_all(["link", "script"]):
            src = tag.get("src", "") or tag.get("href", "")
            m = re.search(r"/wp-content/plugins/([^/]+)/", src)
            if m and m.group(1) not in plugins:
                plugins.append(m.group(1))
        result["plugins_detected"] = plugins

        # WooCommerce
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

            # license.txt → readme_exposed reuse readme flag
            try:
                r = client.head(f"{base}/license.txt")
                if r.status_code == 200:
                    result["readme_exposed"] = True
            except Exception:
                pass

            # User enumeration
            try:
                r = client.get(f"{base}/wp-json/wp/v2/users", timeout=8)
                if r.status_code == 200:
                    data = r.json()
                    if isinstance(data, list) and data:
                        result["user_enumeration_possible"] = True
                        result["exposed_users"] = [u.get("slug", u.get("name", "")) for u in data[:5]]
            except Exception:
                pass

            # WooCommerce API
            if result["woocommerce_detected"]:
                try:
                    r = client.get(f"{base}/wp-json/wc/v3/products", timeout=8)
                    if r.status_code == 200:
                        result["woocommerce_api_public"] = True
                except Exception:
                    pass

        # WP version check
        try:
            r = httpx.get("https://api.wordpress.org/core/version-check/1.7/", timeout=8)
            latest = r.json()["offers"][0]["version"]
            result["wp_version_latest"] = latest
        except Exception:
            pass

        # Plugin vuln check via WPScan
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

        # Build issues
        if result["wp_login_exposed"]:
            issues.append("wp-login.php öffentlich erreichbar")
        if result["xmlrpc_exposed"]:
            issues.append("xmlrpc.php erreichbar (Brute-Force-Risiko)")
        if result["user_enumeration_possible"]:
            issues.append(f"User-Enumeration möglich via REST-API ({', '.join(result['exposed_users'])})")
        if result["readme_exposed"]:
            issues.append("readme.html / license.txt exponiert (Version-Leakage)")
        if result["debug_log_exposed"]:
            issues.append("🔴 KRITISCH: debug.log öffentlich zugänglich")
        if result["wpcron_exposed"]:
            issues.append("wp-cron.php direkt erreichbar")
        if result["plugin_vulns"]:
            for pv in result["plugin_vulns"]:
                issues.append(f"Plugin '{pv['plugin']}' hat {pv['count']} bekannte Schwachstelle(n)")
        if result["woocommerce_api_public"]:
            issues.append("🔴 KRITISCH: WooCommerce REST-API ohne Authentifizierung erreichbar")

        result["issues"] = issues
        return result
    except Exception as e:
        return {"error": str(e)}
