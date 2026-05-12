import json
from bs4 import BeautifulSoup


REQUIRED_FIELDS = {
    "Organization": ["name", "url"],
    "WebSite": ["name", "url"],
    "Article": ["headline", "author", "datePublished"],
    "Product": ["name", "offers"],
    "LocalBusiness": ["name", "address"],
    "FAQPage": ["mainEntity"],
    "BreadcrumbList": ["itemListElement"],
}


def run(url: str, html: str, soup: BeautifulSoup, headers: dict) -> dict:
    try:
        issues = []
        json_ld = []
        json_ld_field_issues = []

        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "")
                schema_type = data.get("@type", "Unknown")
                json_ld.append({"type": schema_type, "raw": data})

                required = REQUIRED_FIELDS.get(schema_type, [])
                for field in required:
                    if field not in data:
                        json_ld_field_issues.append(f"{schema_type}: Pflichtfeld '{field}' fehlt")
            except json.JSONDecodeError:
                issues.append("JSON-LD nicht parsebar")

        microdata_types = list({
            tag.get("itemtype", "") for tag in soup.find_all(attrs={"itemtype": True})
        })

        og_type_tag = soup.find("meta", attrs={"property": "og:type"})
        og_type = og_type_tag.get("content") if og_type_tag else None

        tw = lambda name: (soup.find("meta", attrs={"name": f"twitter:{name}"}) or {}).get("content")
        twitter_card = tw("card")
        twitter_title = tw("title")

        types_found = [item["type"] for item in json_ld]

        if not json_ld:
            issues.append("Kein JSON-LD strukturiertes Daten gefunden")
        else:
            if "WebSite" not in types_found and "Organization" not in types_found:
                issues.append("Kein WebSite- oder Organization-Schema gefunden")
        issues.extend(json_ld_field_issues)
        if not og_type:
            issues.append("og:type fehlt")
        if not twitter_card:
            issues.append("Keine Twitter Card vorhanden")

        return {
            "json_ld": json_ld,
            "json_ld_count": len(json_ld),
            "json_ld_field_issues": json_ld_field_issues,
            "microdata_types": microdata_types,
            "twitter_card": twitter_card,
            "twitter_title": twitter_title,
            "issues": issues,
        }
    except Exception as e:
        return {"error": str(e)}
