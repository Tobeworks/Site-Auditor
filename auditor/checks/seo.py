import httpx
from bs4 import BeautifulSoup
from urllib.parse import urlparse


def run(url: str, html: str, soup: BeautifulSoup, headers: dict) -> dict:
    try:
        issues = []
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

        # Issues
        if not title:
            issues.append("Kein <title>-Tag vorhanden")
        elif title_length < 50:
            issues.append(f"Title zu kurz ({title_length} Zeichen, optimal 50-60)")
        elif title_length > 60:
            issues.append(f"Title zu lang ({title_length} Zeichen, optimal 50-60)")

        if not meta_description:
            issues.append("Keine Meta-Description vorhanden")
        elif meta_description_length < 120:
            issues.append(f"Meta-Description zu kurz ({meta_description_length} Zeichen, optimal 120-160)")
        elif meta_description_length > 160:
            issues.append(f"Meta-Description zu lang ({meta_description_length} Zeichen, optimal 120-160)")

        if h1_count == 0:
            issues.append("Kein H1-Tag vorhanden")
        elif h1_count > 1:
            issues.append(f"Mehrere H1-Tags vorhanden ({h1_count})")

        if not canonical:
            issues.append("Kein Canonical-Tag vorhanden")

        if not og_image:
            issues.append("Kein og:image vorhanden")
        elif og_image_width and og_image_height:
            try:
                if int(og_image_width) < 1200 or int(og_image_height) < 630:
                    issues.append(f"og:image zu klein ({og_image_width}×{og_image_height}px, empfohlen 1200×630)")
            except ValueError:
                pass

        if not og_type:
            issues.append("Kein og:type vorhanden")

        if not twitter_card:
            issues.append("Keine Twitter Card vorhanden")

        if not lang:
            issues.append("HTML lang-Attribut fehlt")

        if not favicon_found:
            issues.append("Kein Favicon gefunden")

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
            "issues": issues,
        }
    except Exception as e:
        return {"error": str(e)}
