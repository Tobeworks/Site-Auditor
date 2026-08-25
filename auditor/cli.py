#!/usr/bin/env python3
import argparse
import os
import sys
import yaml
from dotenv import load_dotenv
load_dotenv(override=True)
from pathlib import Path
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from auditor import __version__
from auditor.runner import run_audit
from auditor import report as report_module
from auditor import summary as summary_module
from auditor.checks import ALL_CHECKS

console = Console()


def load_config() -> dict:
    for path in [Path(".site-auditor.yml"), Path.home() / ".site-auditor.yml"]:
        if path.exists():
            with open(path) as f:
                return yaml.safe_load(f) or {}
    return {}


def _make_progress_handler(progress: Progress):
    """Drives a Rich Progress spinner from runner.run_audit's on_progress callback."""
    task_id = {"current": None}

    def handler(name: str, message: str):
        if task_id["current"] is not None:
            progress.remove_task(task_id["current"])
            task_id["current"] = None

        if name == "start":
            console.print(f"\n[bold cyan]Site Auditor[/bold cyan] → [white]{message}[/white]\n")
        elif name == "error":
            console.print(f"[red]Fehler: {message}[/red]")
        elif name == "warning":
            console.print(f"[yellow]⚠ {message}[/yellow]")
        elif name == "done":
            console.print("\n[bold green]✓ Analyse abgeschlossen[/bold green]\n")
        elif name == "wordpress":
            console.print(f"[dim]→ {message}[/dim]")
        else:
            task_id["current"] = progress.add_task(message, total=None)

    return handler


def main():
    config = load_config()

    parser = argparse.ArgumentParser(
        prog="site-auditor",
        description="Vollständige Website-Analyse mit Markdown-Report",
    )
    parser.add_argument("url", nargs="?", help="URL der zu analysierenden Website")
    parser.add_argument("--output", default=config.get("output", "./reports"), help="Ausgabeverzeichnis")
    parser.add_argument("--skip", default=",".join(config.get("skip", [])), help="Module überspringen (kommasepariert)")
    parser.add_argument("--format", choices=["md", "json", "html"], default=config.get("format", "md"))
    parser.add_argument("--summary", action="store_true", help="KI-Zusammenfassung in Laiensprache generieren")
    parser.add_argument("--list-checks", action="store_true", help="Verfügbare Module auflisten")
    parser.add_argument("--version", action="store_true", help="Version ausgeben")

    args = parser.parse_args()

    if args.version:
        console.print(f"site-auditor v{__version__}")
        sys.exit(0)

    if args.list_checks:
        console.print("\n[bold]Verfügbare Module:[/bold]")
        for check in ALL_CHECKS:
            console.print(f"  - {check}")
        console.print("")
        sys.exit(0)

    if not args.url:
        parser.print_help()
        sys.exit(1)

    # Load API keys from config if not in env
    for key in ["WPSCAN_API_KEY", "SHODAN_API_KEY", "ANTHROPIC_API_KEY"]:
        config_key = key.lower()
        if not os.environ.get(key) and config.get(config_key):
            os.environ[key] = config[config_key]

    skip = [s.strip() for s in args.skip.split(",") if s.strip()] if args.skip else []

    url = args.url
    if not url.startswith("http"):
        url = f"https://{url}"

    # Run audit
    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console) as progress:
        on_progress = _make_progress_handler(progress)
        results = run_audit(url, skip=skip, on_progress=on_progress)
    if not results:
        sys.exit(1)

    # AI summary
    ai_summary = None
    if args.summary:
        ai_summary = summary_module.generate(url, results, on_progress=lambda n, m: console.print(f"[yellow]⚠ {m}[/yellow]" if n == "warning" else f"[dim]→ {m}[/dim]"))

    # Build & save report
    content = report_module.build(url, results, ai_summary=ai_summary, fmt=args.format)
    path = report_module.save(content, url, args.output, fmt=args.format)

    console.print(f"[bold green]Report gespeichert:[/bold green] {path}\n")


if __name__ == "__main__":
    main()
