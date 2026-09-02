import json
import re
from bs4 import BeautifulSoup

from auditor.findings import finding

REQUIRED_FIELDS = {
    "Organization": ["name", "url"],
    "WebSite": ["name", "url"],
    "Article": ["headline", "author", "datePublished"],
    "Product": ["name", "offers"],
    "LocalBusiness": ["name", "address"],
    "FAQPage": ["mainEntity"],
    "BreadcrumbList": ["itemListElement"],
}

RECOMMENDED_FIELDS = {
    "Product": ["sku", "brand", "seller", "priceValidUntil"],
    "Organization": ["logo", "address", "sameAs"],
}

PRICE_RE = re.compile(r"(\d{1,4}[.,]\d{2})\s*€|€\s*(\d{1,4}[.,]\d{2})")
HTML_TAG_RE = re.compile(r"<[a-zA-Z/][^>]*>")


def _visible_prices(text: str) -> set[float]:
    """Best-effort extraction of simple 'XX,XX €' / '€ XX,XX' prices.
    ponytail: no thousands-separator handling, only used to spot obvious mismatches."""
    prices = set()
    for m in PRICE_RE.finditer(text):
        raw = m.group(1) or m.group(2)
        try:
            prices.add(round(float(raw.replace(",", ".")), 2))
        except ValueError:
            pass
    return prices


def _walk_strings(data):
    """Yield every string value found anywhere in a nested dict/list."""
    if isinstance(data, dict):
        for v in data.values():
            yield from _walk_strings(v)
    elif isinstance(data, list):
        for v in data:
            yield from _walk_strings(v)
    elif isinstance(data, str):
        yield data


def _schema_price(data: dict) -> float | None:
    offers = data.get("offers")
    if isinstance(offers, list) and offers:
        offers = offers[0]
    if isinstance(offers, dict):
        price = offers.get("price")
        if price is None:
            return None
        try:
            return float(str(price).replace(",", "."))
        except ValueError:
            return None
    return None


def run(url: str, html: str, soup: BeautifulSoup, headers: dict) -> dict:
    try:
        findings = []
        json_ld = []
        json_ld_field_issues = []
        parse_errors = 0

        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "")
            except json.JSONDecodeError:
                parse_errors += 1
                continue

            schema_type = data.get("@type", "Unknown")
            json_ld.append({"type": schema_type, "raw": data})

            for field in REQUIRED_FIELDS.get(schema_type, []):
                if field not in data:
                    json_ld_field_issues.append(f"{schema_type}: Pflichtfeld '{field}' fehlt")
                    findings.append(finding("SDA-03", "MITTEL",
                        f"{schema_type}-Schema: Pflichtfeld '{field}' fehlt",
                        f"Google kann den {schema_type}-Rich-Result-Typ ohne dieses Feld nicht sicher validieren.",
                        solution=f"Feld '{field}' im {schema_type}-JSON-LD ergänzen."))

            for field in RECOMMENDED_FIELDS.get(schema_type, []):
                if field not in data:
                    findings.append(finding("SDA-04", "MITTEL",
                        f"{schema_type}-Schema: Empfehlungsfeld '{field}' fehlt",
                        f"Ohne '{field}' zeigt Google für {schema_type} eine eingeschränktere Rich-Result-Darstellung (z.B. fehlende Marken-/Verkäuferangabe).",
                        solution=f"Feld '{field}' im {schema_type}-JSON-LD ergänzen, falls verfügbar."))

            if schema_type == "Product":
                schema_price = _schema_price(data)
                if schema_price is not None:
                    visible = _visible_prices(soup.get_text(separator=" "))
                    if len(visible) == 1:
                        visible_price = next(iter(visible))
                        if abs(schema_price - visible_price) > 0.01:
                            findings.append(finding("SDA-07", "HOCH",
                                f"Preis im Schema ({schema_price}) weicht vom sichtbaren Preis ({visible_price}) ab",
                                "Eine Preis-Abweichung zwischen strukturierten Daten und der sichtbaren Seite verstößt gegen Google-Richtlinien und kann zur Rich-Result-Sperre führen.",
                                solution="offers.price im JSON-LD an den tatsächlich angezeigten Preis anpassen."))
                        else:
                            findings.append(finding("SDA-07", "POSITIV",
                                "Preis im Schema stimmt mit dem sichtbaren Preis überein",
                                "Konsistente Preisangabe erfüllt die Google-Richtlinien für Rich Results."))

        for _ in range(parse_errors):
            findings.append(finding("SDA-01", "MITTEL", "JSON-LD-Block nicht parsebar (ungültiges JSON)",
                "Fehlerhaftes JSON-LD wird von Google ignoriert — Rich Results für diesen Block entfallen komplett.",
                solution='JSON in diesem <script type="application/ld+json">-Block auf Syntaxfehler prüfen, z.B. mit einem JSON-Validator.'))

        microdata_types = list({
            tag.get("itemtype", "") for tag in soup.find_all(attrs={"itemtype": True})
        })

        types_found = [item["type"] for item in json_ld]

        # SDA-02 Basis-Schema
        if not json_ld:
            findings.append(finding("SDA-02", "HOCH", "Kein JSON-LD strukturiertes Datenformat gefunden",
                "Ohne strukturierte Daten kann Google keine Rich Results (Sterne, Preis, Breadcrumbs etc.) in der Suche anzeigen.",
                solution="Mindestens ein WebSite- oder Organization-Schema als JSON-LD im <head> ergänzen."))
        elif "WebSite" not in types_found and "Organization" not in types_found:
            findings.append(finding("SDA-02", "MITTEL", "Kein WebSite- oder Organization-Schema gefunden",
                "Fehlende Basis-Schemas erschweren es Google, die Seite eindeutig einer Marke/Organisation zuzuordnen.",
                solution="WebSite- und/oder Organization-Schema als JSON-LD ergänzen."))
        else:
            findings.append(finding("SDA-02", "POSITIV", "WebSite- oder Organization-Schema vorhanden",
                "Google kann die Seite der richtigen Marke/Organisation zuordnen."))

        if json_ld and not json_ld_field_issues:
            findings.append(finding("SDA-03", "POSITIV", "Alle geprüften Pflichtfelder sind vorhanden",
                "Erkannte Schema-Typen erfüllen die Mindestanforderungen für Rich Results."))

        all_strings = {s for d in json_ld for s in _walk_strings(d["raw"])}

        # SDA-05 Protokoll-Konsistenz
        http_urls = [s for s in all_strings if s.startswith("http://")]
        if http_urls:
            findings.append(finding("SDA-05", "MITTEL", f"{len(http_urls)} http://-URL(s) in JSON-LD gefunden",
                "Unverschlüsselte URLs in strukturierten Daten auf einer HTTPS-Seite sind inkonsistent und können bei Bildern zu Mixed-Content-Warnungen führen.",
                solution="Alle URLs in den JSON-LD-Feldern auf https:// umstellen."))

        # SDA-06 Rohes HTML in Textfeldern
        raw_html_fields = [s for s in all_strings if HTML_TAG_RE.search(s)]
        if raw_html_fields:
            findings.append(finding("SDA-06", "MITTEL", f"{len(raw_html_fields)} Textfeld(er) mit rohem HTML im JSON-LD",
                "Rohes HTML (z.B. <br />) in Textfeldern wie 'description' wird von Google im Klartext angezeigt und wirkt unsauber.",
                solution="HTML-Tags aus JSON-LD-Textfeldern entfernen, reinen Text verwenden."))

        # SDA-08 Breadcrumb-Konsistenz
        visible_breadcrumb = soup.select_one('nav[aria-label*="breadcrumb" i], .breadcrumb, .breadcrumbs') is not None
        has_breadcrumb_schema = "BreadcrumbList" in types_found
        if visible_breadcrumb and not has_breadcrumb_schema:
            findings.append(finding("SDA-08", "MITTEL", "Sichtbare Breadcrumb-Navigation ohne BreadcrumbList-Schema",
                "Ohne BreadcrumbList-Schema kann Google die Breadcrumb nicht als Rich-Result-Pfad in der Suche anzeigen.",
                solution="BreadcrumbList-Schema passend zur sichtbaren Breadcrumb-Navigation als JSON-LD ergänzen."))
        elif visible_breadcrumb and has_breadcrumb_schema:
            findings.append(finding("SDA-08", "POSITIV", "Sichtbare Breadcrumb hat passendes BreadcrumbList-Schema",
                "Google kann den Navigationspfad als Rich Result anzeigen."))

        return {
            "json_ld": json_ld,
            "json_ld_count": len(json_ld),
            "json_ld_field_issues": json_ld_field_issues,
            "microdata_types": microdata_types,
            "findings": findings,
        }
    except Exception as e:
        return {"error": str(e)}
