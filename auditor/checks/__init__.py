# Einzige Quelle der Wahrheit für verfügbare Check-Module (Reihenfolge = Ausführungsreihenfolge
# der sequenziellen Pipeline in auditor/runner.py, siehe dort für Sonderfälle wie
# wordpress/wordpress_deep/hosting/dns/a11y).
ALL_CHECKS = [
    "wordpress", "wordpress_deep", "seo", "security", "performance",
    "broken_links", "structured_data", "markup", "legal", "tech_stack",
    "social", "hosting", "dns", "content_quality", "a11y",
]
