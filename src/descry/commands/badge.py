"""swain badge — print a shields.io README badge for the current scan status."""

from __future__ import annotations

from pathlib import Path

from rich.console import Console

from descry.commands.launch_card import build_launch_card_data
from descry.commands.share import badge_markdown

console = Console()


def run_badge(repo_root: Path) -> None:
    profile_path = repo_root / ".swain" / "profile.yaml"
    if not profile_path.exists():
        console.print(
            "[yellow]No .swain/profile.yaml found. "
            "Run [bold]swain scan[/bold] first.[/yellow]"
        )
        return

    data = build_launch_card_data(repo_root)
    md = badge_markdown(data)
    verdict_color = {
        "READY": "green",
        "BLOCKED": "red",
        "REVIEW": "yellow",
    }.get(data.verdict, "dim")

    console.print()
    console.print(
        f"[bold]Verdict:[/bold] [{verdict_color}]{data.verdict}[/{verdict_color}]  "
        f"[dim]{data.open_findings} finding(s), "
        f"{data.launch_blockers} blocker(s)[/dim]"
    )
    console.print()
    console.print("[bold]Markdown:[/bold]")
    console.print(f"  [cyan]{md}[/cyan]")
    console.print()
    console.print("[dim]Paste into your README to show your live scan verdict.[/dim]")
