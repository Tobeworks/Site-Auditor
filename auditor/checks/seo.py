import httpx
from bs4 import BeautifulSoup
from urllib.parse import urlparse

from auditor.findings import finding


def run(url: str, html: str, soup: BeautifulSoup, headers: dict) -> dict:
    try:
        findings = []
        base = f"{urlparse(url).scheme}://{urlparse(url).netloc}"

        # Title
        title_tag = soup.find("title")
        title = title_tag.get_text(strip=True) if title_tag else None
        title_length = len(title) if title else 0

        # Meta description
        desc_tag = soup.find("meta", attrs={"name": "description"})
        meta_description = desc_tag.get("content", "").strip() if desc_tag else None
        meta_description_length = len(meta_description) if meta_description else 0

        # H1
        h1_tags = [h.get_text(strip=True) for h in soup.find_all("h1")]
        h1_count = len(h1_tags)

        # Canonical
        canonical_tag = soup.find("link", attrs={"rel": "canonical"})
        canonical = canonical_tag.get("href") if canonical_tag else None

        # OG tags
        def og(prop):
            tag = soup.find("meta", attrs={"property": f"og:{prop}"})
            return tag.get("content") if tag else None

        og_title = og("title")
        og_description = og("description")
        og_image = og("image")
        og_type = og("type")
        og_image_width = og("image:width")
        og_image_height = og("image:height")

        # Twitter
        def tw(name):
            tag = soup.find("meta", attrs={"name": f"twitter:{name}"})
            return tag.get("content") if tag else None

        twitter_card = tw("card")
        twitter_title = tw("title")
        twitter_description = tw("description")
        twitter_image = tw("image")

        # Robots meta
        robots_tag = soup.find("meta", attrs={"name": "robots"})
        robots_meta = robots_tag.get("content") if robots_tag else None

        # Lang
        html_tag = soup.find("html")
        lang = html_tag.get("lang") if html_tag else None

        # Favicon
        favicon_found = False
        favicon_link = soup.find("link", attrs={"rel": lambda r: r and "icon" in r.lower().split()})
        if favicon_link:
            favicon_found = True
        else:
            try:
                r = httpx.head(f"{base}/favicon.ico", timeout=5, follow_redirects=True)
                favicon_found = r.status_code == 200
            except Exception:
                pass

        # Apple touch icon
        apple_touch = soup.find("link", attrs={"rel": lambda r: r and "apple-touch-icon" in (r if isinstance(r, str) else " ".join(r))})
        apple_touch_icon_found = apple_touch is not None

        # Web App Manifest
        manifest_tag = soup.find("link", attrs={"rel": "manifest"})
        web_app_manifest_found = False
        if manifest_tag:
            web_app_manifest_found = True
        else:
            try:
                r = httpx.head(f"{base}/manifest.json", timeout=5, follow_redirects=True)
                web_app_manifest_found = r.status_code == 200
            except Exception:
                pass

        # SEO-01 Title
        if not title:
            findings.append(finding("SEO-01", "HOCH", "Kein <title>-Tag vorhanden",
                "Ohne Title-Tag generiert Google den Snippet-Text automatisch aus dem Seiteninhalt — Klickrate und Keyword-Relevanz in der Suche leiden.",
                solution="Einen aussagekräftigen <title>-Tag mit 50-60 Zeichen ergänzen: Kernkeyword + Nutzenversprechen."))
        elif title_length < 50:
            findings.append(finding("SEO-01", "MITTEL", f"Title zu kurz ({title_length} Zeichen, optimal 50-60)",
                "Ungenutztes Zeichen-Budget im Suchergebnis — weniger Platz für Keywords und Nutzenversprechen.",
                solution="Title auf 50-60 Zeichen erweitern, z.B. um Marke oder Nutzenversprechen."))
        elif title_length > 60:
            findings.append(finding("SEO-01", "MITTEL", f"Title zu lang ({title_length} Zeichen, optimal 50-60)",
                "Google kürzt den Titel im Suchergebnis ab, wichtige Wörter am Ende gehen verloren.",
                solution="Title auf 50-60 Zeichen kürzen, wichtigste Begriffe nach vorne stellen."))
        else:
            findings.append(finding("SEO-01", "POSITIV", f"Title-Länge optimal ({title_length} Zeichen)",
                "Titel wird in der Suche vollständig angezeigt."))

        # SEO-02 Meta-Description
        if not meta_description:
            findings.append(finding("SEO-02", "MITTEL", "Keine Meta-Description vorhanden",
                "Google generiert den Beschreibungstext im Suchergebnis automatisch aus dem Seiteninhalt — weniger Kontrolle über die Klickrate.",
                solution="Meta-Description mit 120-160 Zeichen ergänzen, die zum Klick motiviert."))
        elif meta_description_length < 120:
            findings.append(finding("SEO-02", "MITTEL", f"Meta-Description zu kurz ({meta_description_length} Zeichen, optimal 120-160)",
                "Ungenutztes Zeichen-Budget im Suchergebnis-Snippet.",
                solution="Meta-Description auf 120-160 Zeichen erweitern."))
        elif meta_description_length > 160:
            findings.append(finding("SEO-02", "MITTEL", f"Meta-Description zu lang ({meta_description_length} Zeichen, optimal 120-160)",
                "Google kürzt die Beschreibung im Suchergebnis ab.",
                solution="Meta-Description auf 120-160 Zeichen kürzen."))
        else:
            findings.append(finding("SEO-02", "POSITIV", f"Meta-Description-Länge optimal ({meta_description_length} Zeichen)",
                "Beschreibung wird im Suchergebnis vollständig angezeigt."))

        # SEO-03 H1
        if h1_count == 0:
            findings.append(finding("SEO-03", "HOCH", "Kein H1-Tag vorhanden",
                "Fehlt die Haupt-Überschrift, verliert Google ein wichtiges Signal für das Seitenthema.",
                solution="Eine einzelne, thema-beschreibende H1-Überschrift ergänzen."))
        elif h1_count > 1:
            findings.append(finding("SEO-03", "MITTEL", f"Mehrere H1-Tags vorhanden ({h1_count})",
                "Mehrere H1 verwässern das thematische Signal für die Seite.",
                solution="Nur eine H1 pro Seite verwenden, weitere Überschriften auf H2/H3 umstellen."))
        else:
            findings.append(finding("SEO-03", "POSITIV", "Genau eine H1 vorhanden",
                "Klares thematisches Signal für Suchmaschinen."))

        # SEO-04 Canonical
        if not canonical:
            findings.append(finding("SEO-04", "HOCH", "Kein Canonical-Tag vorhanden",
                "Ohne Canonical kann Google bei mehreren erreichbaren URL-Varianten der Seite die falsche als Referenz indexieren oder Ranking-Signale aufteilen.",
                solution="<link rel=\"canonical\" href=\"...\"> mit der bevorzugten URL im <head> ergänzen."))
        else:
            findings.append(finding("SEO-04", "POSITIV", "Canonical-Tag vorhanden",
                "Google erhält ein klares Signal für die bevorzugte URL."))

        # SEO-05 og:image
        if not og_image:
            findings.append(finding("SEO-05", "MITTEL", "Kein og:image vorhanden",
                "Beim Teilen in sozialen Netzwerken/Messengern wird kein Vorschaubild angezeigt — geringere Klickrate.",
                solution="og:image mit mind. 1200×630px ergänzen."))
        else:
            small = False
            if og_image_width and og_image_height:
                try:
                    small = int(og_image_width) < 1200 or int(og_image_height) < 630
                except ValueError:
                    pass
            if small:
                findings.append(finding("SEO-05", "MITTEL", f"og:image zu klein ({og_image_width}×{og_image_height}px, empfohlen 1200×630)",
                    "Kleine Vorschaubilder werden auf manchen Plattformen verpixelt oder gar nicht angezeigt.",
                    solution="og:image auf mindestens 1200×630px vergrößern."))
            else:
                findings.append(finding("SEO-05", "POSITIV", "og:image vorhanden und ausreichend groß",
                    "Vorschaubild wird beim Teilen korrekt angezeigt."))

        # SEO-06 og:type
        if not og_type:
            findings.append(finding("SEO-06", "MITTEL", "Kein og:type vorhanden",
                "Ohne og:type wählen Plattformen beim Teilen einen generischen Vorschau-Typ.",
                solution="og:type ergänzen, z.B. \"website\" oder \"article\"."))
        else:
            findings.append(finding("SEO-06", "POSITIV", f"og:type gesetzt ({og_type})",
                "Plattformen zeigen den passenden Vorschau-Typ beim Teilen."))

        # SEO-07 Twitter Card
        if not twitter_card:
            findings.append(finding("SEO-07", "MITTEL", "Keine Twitter Card vorhanden",
                "Ohne Twitter-Card-Tags fällt X/Twitter beim Teilen auf eine einfache Link-Vorschau ohne Bild zurück.",
                solution="twitter:card (z.B. \"summary_large_image\") ergänzen."))
        else:
            findings.append(finding("SEO-07", "POSITIV", f"Twitter Card gesetzt ({twitter_card})",
                "Vorschau auf X/Twitter wird korrekt gerendert."))

        # SEO-08 HTML lang
        if not lang:
            findings.append(finding("SEO-08", "MITTEL", "HTML lang-Attribut fehlt",
                "Suchmaschinen und Screenreader können die Sprache der Seite nicht sicher bestimmen.",
                solution="lang-Attribut am <html>-Tag setzen, z.B. lang=\"de\"."))
        else:
            findings.append(finding("SEO-08", "POSITIV", f"HTML lang-Attribut gesetzt ({lang})",
                "Sprache der Seite ist eindeutig maschinenlesbar."))

        # SEO-09 Favicon
        if not favicon_found:
            findings.append(finding("SEO-09", "MITTEL", "Kein Favicon gefunden",
                "Fehlendes Favicon wirkt in Browser-Tabs und Lesezeichen unprofessionell.",
                solution="Favicon als <link rel=\"icon\"> im <head> einbinden oder unter /favicon.ico bereitstellen."))
        else:
            findings.append(finding("SEO-09", "POSITIV", "Favicon vorhanden", "Browser-Tab und Lesezeichen zeigen ein Icon."))

        return {
            "title": title,
            "title_length": title_length,
            "meta_description": meta_description,
            "meta_description_length": meta_description_length,
            "h1_tags": h1_tags,
            "h1_count": h1_count,
            "canonical": canonical,
            "og_title": og_title,
            "og_description": og_description,
            "og_image": og_image,
            "og_image_width": og_image_width,
            "og_image_height": og_image_height,
            "og_type": og_type,
            "twitter_card": twitter_card,
            "twitter_title": twitter_title,
            "twitter_description": twitter_description,
            "twitter_image": twitter_image,
            "robots_meta": robots_meta,
            "lang": lang,
            "favicon_found": favicon_found,
            "apple_touch_icon_found": apple_touch_icon_found,
            "web_app_manifest_found": web_app_manifest_found,
            "findings": findings,
        }
    except Exception as e:
        return {"error": str(e)}
