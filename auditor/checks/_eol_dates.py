"""Static PHP end-of-life table (major.minor -> security-support-end date), hand-maintained.
Source: https://www.php.net/supported-versions.php (aktive Branches, Spalte "Security Support Until")
und https://www.php.net/eol.php (bereits abgelaufene Branches) — last checked 2026-09-03.
No live API call by design (avoids an extra network dependency for a slow-moving table);
extend/update this dict by hand when php.net publishes new dates."""

PHP_EOL_DATES = {
    "7.2": "2020-11-30",
    "7.3": "2021-12-06",
    "7.4": "2022-11-28",
    "8.0": "2023-11-26",
    "8.1": "2025-12-31",
    "8.2": "2026-12-31",
    "8.3": "2027-12-31",
    "8.4": "2028-12-31",
    "8.5": "2029-12-31",
}
