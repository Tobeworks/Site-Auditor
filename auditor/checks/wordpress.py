import re
from bs4 import BeautifulSoup


def run(url: str, html: str, soup: BeautifulSoup, headers: dict) -> dict:
    try:
        is_wordpress = False
        version = None
        theme = None
        plugins = []

        if "/wp-content/" in html or "/wp-includes/" in html:
            is_wordpress = True

        powered_by = headers.get("x-powered-by", "")
        if "wordpress" in powered_by.lower():
            is_wordpress = True

        generator = soup.find("meta", attrs={"name": "generator"})
        if generator:
            content = generator.get("content", "")
            if "WordPress" in content:
                is_wordpress = True
                m = re.search(r"WordPress\s+([\d.]+)", content)
                if m:
                    version = m.group(1)

        if is_wordpress:
            for tag in soup.find_all(["link", "script"], src=True):
                src = tag.get("src", "") or tag.get("href", "")
                m = re.search(r"/wp-content/themes/([^/]+)/", src)
                if m and not theme:
                    theme = m.group(1)
                m = re.search(r"/wp-content/plugins/([^/]+)/", src)
                if m and m.group(1) not in plugins:
                    plugins.append(m.group(1))
            for tag in soup.find_all("link", href=True):
                href = tag.get("href", "")
                m = re.search(r"/wp-content/themes/([^/]+)/", href)
                if m and not theme:
                    theme = m.group(1)
                m = re.search(r"/wp-content/plugins/([^/]+)/", href)
                if m and m.group(1) not in plugins:
                    plugins.append(m.group(1))

        return {
            "is_wordpress": is_wordpress,
            "version": version,
            "theme": theme,
            "plugins": plugins,
            "findings": [],
        }
    except Exception as e:
        return {"error": str(e)}
