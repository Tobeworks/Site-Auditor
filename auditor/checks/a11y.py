import asyncio
from bs4 import BeautifulSoup


async def _run_axe(url: str) -> dict:
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.launch(args=["--no-sandbox"])
        page = await browser.new_page()
        await page.goto(url, timeout=30000)
        await page.add_script_tag(url="https://cdnjs.cloudflare.com/ajax/libs/axe-core/4.9.1/axe.min.js")
        results = await page.evaluate("axe.run()")
        await browser.close()
        return results


def run(url: str, html: str, soup: BeautifulSoup, headers: dict) -> dict:
    try:
        issues = []

        # axe-core
        axe_results = asyncio.run(_run_axe(url))
        raw_violations = axe_results.get("violations", [])
        incomplete = axe_results.get("incomplete", [])

        violations = []
        counts = {"critical": 0, "serious": 0, "moderate": 0, "minor": 0}
        for v in raw_violations:
            impact = v.get("impact", "minor")
            counts[impact] = counts.get(impact, 0) + 1
            wcag = next((t for t in v.get("tags", []) if t.startswith("wcag")), "")
            example_selector = ""
            if v.get("nodes"):
                example_selector = v["nodes"][0].get("target", [""])[0] if v["nodes"][0].get("target") else ""
            violations.append({
                "id": v.get("id", ""),
                "impact": impact,
                "wcag": wcag,
                "description": v.get("description", ""),
                "affected_elements": len(v.get("nodes", [])),
                "example_selector": example_selector,
            })

        # Manual DOM checks
        images_without_alt = 0
        for img in soup.find_all("img"):
            alt = img.get("alt")
            role = img.get("role", "")
            if alt is None or (alt == "" and role != "presentation"):
                images_without_alt += 1

        unlabeled_inputs = 0
        for inp in soup.find_all(["input", "select", "textarea"]):
            if inp.get("type") == "hidden":
                continue
            inp_id = inp.get("id")
            has_label = bool(inp_id and soup.find("label", attrs={"for": inp_id}))
            has_aria = bool(inp.get("aria-label") or inp.get("aria-labelledby"))
            if not has_label and not has_aria:
                unlabeled_inputs += 1

        generic_texts = {"hier", "mehr", "click here", "read more", "weiter", "more", "details", "link"}
        generic_link_texts = []
        for a in soup.find_all("a"):
            text = a.get_text(strip=True).lower()
            if text in generic_texts:
                generic_link_texts.append(a.get_text(strip=True))

        # Heading hierarchy
        heading_hierarchy_issues = []
        headings = [int(h.name[1]) for h in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"])]
        for i in range(1, len(headings)):
            if headings[i] - headings[i - 1] > 1:
                heading_hierarchy_issues.append(f"Sprung von H{headings[i-1]} zu H{headings[i]}")

        # Focus outline suppression
        focus_outline_suppressed = False
        for style in soup.find_all("style"):
            text = style.get_text()
            if "outline: none" in text or "outline: 0" in text or "outline:none" in text or "outline:0" in text:
                focus_outline_suppressed = True
                break

        html_tag = soup.find("html")
        lang_attribute = html_tag.get("lang") if html_tag else None

        # Build issues
        total_violations = sum(counts.values())
        if counts["critical"] > 0:
            issues.append(f"{counts['critical']} kritische Barrierefreiheits-Verstöße (WCAG)")
        if counts["serious"] > 0:
            issues.append(f"{counts['serious']} schwerwiegende Barrierefreiheits-Verstöße")
        if images_without_alt > 0:
            issues.append(f"{images_without_alt} Bild(er) ohne Alt-Text")
        if unlabeled_inputs > 0:
            issues.append(f"{unlabeled_inputs} Formularfeld(er) ohne Label")
        if generic_link_texts:
            issues.append(f"Generische Linktexte gefunden: {', '.join(set(generic_link_texts))}")
        if heading_hierarchy_issues:
            issues.append(f"Überschriften-Hierarchie-Probleme: {'; '.join(heading_hierarchy_issues[:3])}")
        if focus_outline_suppressed:
            issues.append("Focus-Outline unterdrückt (outline:none/0 in CSS)")
        if not lang_attribute:
            issues.append("HTML lang-Attribut fehlt")

        return {
            "violations": violations,
            "incomplete": [{"id": v.get("id"), "description": v.get("description")} for v in incomplete[:10]],
            "violations_count": counts,
            "manual_checks": {
                "images_without_alt": images_without_alt,
                "unlabeled_inputs": unlabeled_inputs,
                "generic_link_texts": list(set(generic_link_texts)),
                "heading_hierarchy_issues": heading_hierarchy_issues,
                "focus_outline_suppressed": focus_outline_suppressed,
                "lang_attribute": lang_attribute,
            },
            "issues": issues,
        }
    except Exception as e:
        return {"error": str(e)}
