import httpx
from bs4 import BeautifulSoup
from urllib.parse import urlparse

from auditor.findings import finding
from auditor.checks._iso_codes import ISO_639_1, ISO_3166_1


def _parse_robots_groups(text: str) -> list[dict]:
    """Group robots.txt lines into {'agents': [...], 'disallow': [...]} blocks.
    ponytail: agents are grouped by consecutive User-agent lines before any
    Disallow line, per the common robots.txt convention — not a full RFC parser."""
    groups = []
    current_agents: list[str] = []
    current_rules: list[str] = []

    def flush():
        if current_agents:
            groups.append({"agents": current_agents[:], "disallow": current_rules[:]})

    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip().lower()
        value = value.strip()
        if key == "user-agent":
            if current_rules:
                flush()
                current_agents = []
                current_rules = []
            current_agents.append(value)
        elif key == "disallow" and value:
            current_rules.append(value)
    flush()
    return groups


def _validate_hreflang(value: str) -> bool:
    if value.lower() == "x-default":
        return True
    parts = value.split("-")
    if parts[0].lower() not in ISO_639_1:
        return False
    if len(parts) > 1:
        sub = parts[1]
        # BCP-47: 4 Buchstaben = Script-Subtag (z. B. zh-Hant) — Form genügt, keine Liste
        if len(sub) == 4 and sub.isalpha():
            return True
        if sub.lower() not in ISO_3166_1:
            return False
    return True


def run(url: str, html: str, soup: BeautifulSoup, headers: dict) -> dict:
    try:
        findings = []
        base = f"{urlparse(url).scheme}://{urlparse(url).netloc}"

        # Canonical consistency
        canonical_tag = soup.find("link", attrs={"rel": "canonical"})
        canonical = canonical_tag.get("href") if canonical_tag else None
        canonical_matches = canonical == url if canonical else False

        # Hreflang
        hreflang_tags = []
        for tag in soup.find_all("link", rel="alternate"):
            lang = tag.get("hreflang")
            if lang:
                hreflang_tags.append({"lang": lang, "href": tag.get("href", "")})
        hreflang_x_default = any(t["lang"].lower() == "x-default" for t in hreflang_tags)

        sitemap_urls = []
        robots_txt_found = False
        robots_disallow_all = False
        robots_wp_admin_blocked = False
        robots_sitemap_referenced = False
        robots_text = ""
        feed_urls = []

        with httpx.Client(timeout=8, headers={"User-Agent": "Mozilla/5.0"}) as client:
            for path in ["/sitemap.xml", "/sitemap_index.xml", "/wp-sitemap.xml"]:
                try:
                    r = client.head(f"{base}{path}")
                    if r.status_code in (200, 301, 302):
                        sitemap_urls.append(f"{base}{path}")
                except Exception:
                    pass

            try:
                r = client.get(f"{base}/robots.txt")
                if r.status_code == 200:
                    robots_txt_found = True
                    robots_text = r.text
                    robots_content = robots_text.lower()
                    for line in robots_text.splitlines():
                        if line.strip().lower() == "disallow: /":
                            robots_disallow_all = True
                            break
                    robots_wp_admin_blocked = "disallow: /wp-admin" in robots_content
                    robots_sitemap_referenced = "sitemap:" in robots_content
            except Exception:
                pass

            for tag in soup.find_all("link", rel="alternate"):
                link_type = tag.get("type", "")
                if "rss" in link_type or "atom" in link_type:
                    href = tag.get("href", "")
                    if href:
                        feed_urls.append(href)
            if not feed_urls:
                for path in ["/feed", "/rss.xml", "/atom.xml", "/feed.xml"]:
                    try:
                        r = client.head(f"{base}{path}")
                        if r.status_code == 200:
                            feed_urls.append(f"{base}{path}")
                    except Exception:
                        pass

            # SOC-09 hreflang Rückverweis (max. 5 Ziele, Kostenbegrenzung)
            targets = [t["href"] for t in hreflang_tags
                       if t["lang"].lower() != "x-default" and t["href"] and t["href"] != url][:5]
            backlink_missing = []
            for target in targets:
                try:
                    r = client.get(target)
                    if r.status_code >= 400:
                        backlink_missing.append(target)
                        continue
                    target_soup = BeautifulSoup(r.text, "lxml")
                    back_hrefs = {t.get("href", "") for t in target_soup.find_all("link", rel="alternate") if t.get("hreflang")}
                    if url not in back_hrefs:
                        backlink_missing.append(target)
                except Exception:
                    backlink_missing.append(target)

        # SOC-01 robots.txt vorhanden / Disallow-All
        if not robots_txt_found:
            findings.append(finding("SOC-01", "MITTEL", "robots.txt nicht gefunden",
                "Ohne robots.txt haben Crawler keine Steuerungsanweisungen — Standardverhalten greift, das nicht immer gewünscht ist.",
                solution="robots.txt im Root-Verzeichnis bereitstellen, mindestens mit einem Sitemap-Verweis."))
        elif robots_disallow_all:
            findings.append(finding("SOC-01", "KRITISCH", "robots.txt blockiert alle Crawler (Disallow: /)",
                "Die komplette Seite ist für Suchmaschinen gesperrt — kein organischer Traffic möglich.",
                solution="Disallow: / aus der *-Gruppe entfernen bzw. auf die tatsächlich zu sperrenden Pfade beschränken."))
        else:
            findings.append(finding("SOC-01", "POSITIV", "robots.txt vorhanden und sperrt nicht global",
                "Crawler können die Seite regulär crawlen."))

        # SOC-02 /wp-admin/ blockiert
        if "/wp-content/" in html:
            if not robots_wp_admin_blocked:
                findings.append(finding("SOC-02", "MITTEL", "/wp-admin/ nicht in robots.txt blockiert",
                    "wp-admin kann von Crawlern besucht/indexiert werden — unnötige Crawl-Last auf Backend-Seiten.",
                    solution="Disallow: /wp-admin/ in der *-Gruppe der robots.txt ergänzen (Allow: /wp-admin/admin-ajax.php falls benötigt)."))
            else:
                findings.append(finding("SOC-02", "POSITIV", "/wp-admin/ ist in robots.txt blockiert",
                    "Backend-Bereich wird nicht unnötig gecrawlt."))

        # SOC-03 Sitemap vorhanden
        if not sitemap_urls:
            findings.append(finding("SOC-03", "MITTEL", "Keine Sitemap gefunden",
                "Ohne Sitemap müssen Suchmaschinen alle Seiten über interne Links entdecken — neue/tief verschachtelte Seiten werden langsamer indexiert.",
                solution="XML-Sitemap generieren (z.B. /sitemap.xml) und über robots.txt referenzieren."))
        else:
            findings.append(finding("SOC-03", "POSITIV", f"Sitemap gefunden ({', '.join(sitemap_urls)})",
                "Suchmaschinen können neue/geänderte Seiten gezielt entdecken."))

        # SOC-04 Sitemap in robots.txt referenziert
        if sitemap_urls and not robots_sitemap_referenced:
            findings.append(finding("SOC-04", "MITTEL", "Sitemap nicht in robots.txt referenziert",
                "Suchmaschinen müssen die Sitemap-URL erraten oder manuell in der Search Console eintragen.",
                solution="Sitemap:-Zeile mit vollständiger URL in die robots.txt ergänzen."))
        elif sitemap_urls:
            findings.append(finding("SOC-04", "POSITIV", "Sitemap ist in robots.txt referenziert",
                "Crawler finden die Sitemap automatisch über robots.txt."))

        # SOC-05 Canonical-Konsistenz
        if canonical:
            if not canonical_matches:
                findings.append(finding("SOC-05", "MITTEL", "Canonical-URL stimmt nicht mit der aufgerufenen URL überein",
                    "Bei abweichendem Canonical wird ggf. eine andere URL als die aufgerufene indexiert.",
                    solution="Prüfen, ob die Seite wirklich auf eine andere URL verweisen soll; falls nicht, Canonical korrigieren."))
            else:
                findings.append(finding("SOC-05", "POSITIV", "Canonical-URL stimmt mit der aufgerufenen URL überein",
                    "Kein Widerspruch zwischen aufgerufener und kanonischer URL."))

        # SOC-06 robots.txt Bot-Gruppen
        if robots_txt_found:
            groups = _parse_robots_groups(robots_text)
            star_groups = [g for g in groups if "*" in g["agents"]]
            star_disallow: set[str] = set()
            for g in star_groups:
                star_disallow.update(g["disallow"])

            if len(star_groups) > 1:
                findings.append(finding("SOC-06", "HOCH", f"robots.txt enthält {len(star_groups)} User-agent: *-Blöcke",
                    "Mehrere *-Gruppen sind mehrdeutig — Crawler-Implementierungen können sie unterschiedlich (z.B. nur die erste oder nur die letzte) auswerten.",
                    solution="Alle Regeln für User-agent: * in einem einzigen Block zusammenführen."))

            weaker_found = False
            bot_names = {"googlebot", "bingbot"}
            for g in groups:
                agents_lower = {a.lower() for a in g["agents"]}
                if agents_lower & bot_names and "*" not in agents_lower:
                    freed = sorted(star_disallow - set(g["disallow"]))
                    if freed:
                        weaker_found = True
                        findings.append(finding("SOC-06", "MITTEL",
                            f"Bot-Gruppe '{', '.join(g['agents'])}' hat schwächere Regeln als die *-Gruppe (freigegeben: {', '.join(freed[:5])})",
                            "Crawler werten nur die für sie spezifischste Gruppe aus — diese Bots dürfen Pfade crawlen, die für alle anderen Crawler gesperrt sind.",
                            solution="Disallow-Regeln der bot-spezifischen Gruppe an die *-Gruppe angleichen, falls die Freigabe nicht beabsichtigt ist."))

            if len(star_groups) <= 1 and not weaker_found:
                findings.append(finding("SOC-06", "POSITIV", "robots.txt ist eindeutig und konsistent über alle Bot-Gruppen",
                    "Keine widersprüchlichen oder mehrdeutigen Bot-Gruppen gefunden."))

        # SOC-07 hreflang ISO-Validität
        invalid_hreflang = [t["lang"] for t in hreflang_tags if not _validate_hreflang(t["lang"])]
        if invalid_hreflang:
            findings.append(finding("SOC-07", "MITTEL", f"Unbekannter Sprach-/Ländercode in hreflang: {', '.join(invalid_hreflang)}",
                "Der Wert enthält einen Code, den es in ISO-639-1 (Sprache) bzw. ISO-3166-1 (Land) nicht gibt — Suchmaschinen ignorieren solche Einträge, die internationale Ausrichtung greift dafür nicht.",
                solution="Betroffene Codes gegen ISO-639-1 (Sprache) und ISO-3166-1 alpha-2 (Land) prüfen und auf die korrekte Schreibweise korrigieren."))
        elif hreflang_tags:
            findings.append(finding("SOC-07", "POSITIV", "Alle hreflang-Codes sind bekannte ISO-Codes",
                "Sprach-, Länder- und Script-Codes der hreflang-Einträge entsprechen ISO-639-1/ISO-3166-1 bzw. gültigen BCP-47-Script-Subtags."))

        # SOC-08 hreflang x-default
        if hreflang_tags:
            if not hreflang_x_default:
                findings.append(finding("SOC-08", "MITTEL", "Kein x-default hreflang-Eintrag vorhanden",
                    "Nutzer aus nicht explizit abgedeckten Sprach-/Regionen bekommen keine klare Fallback-Seite zugewiesen.",
                    solution='hreflang="x-default" auf die Standard-/Sprachauswahl-Seite ergänzen.'))
            else:
                findings.append(finding("SOC-08", "POSITIV", "x-default hreflang-Eintrag vorhanden",
                    "Klarer Fallback für nicht abgedeckte Sprachen/Regionen ist definiert."))

        # SOC-09 hreflang Rückverweis
        if targets:
            if backlink_missing:
                findings.append(finding("SOC-09", "HOCH", f"{len(backlink_missing)} von {len(targets)} hreflang-Zielen verweisen nicht zurück",
                    "Fehlt der Rückverweis, kann Google das hreflang-Cluster als ungültig behandeln und ignoriert die Sprach-/Regions-Zuordnung ganz.",
                    solution="Auf jeder verlinkten Zielseite einen hreflang-Rückverweis auf diese Seite ergänzen."))
            else:
                findings.append(finding("SOC-09", "POSITIV", "Alle geprüften hreflang-Ziele verweisen korrekt zurück",
                    "hreflang-Cluster ist bidirektional konsistent."))

        return {
            "canonical_matches": canonical_matches,
            "hreflang_tags": hreflang_tags,
            "hreflang_x_default": hreflang_x_default,
            "sitemap_urls": sitemap_urls,
            "robots_txt_found": robots_txt_found,
            "robots_disallow_all": robots_disallow_all,
            "robots_wp_admin_blocked": robots_wp_admin_blocked,
            "robots_sitemap_referenced": robots_sitemap_referenced,
            "feed_urls": feed_urls,
            "findings": findings,
        }
    except Exception as e:
        return {"error": str(e)}
