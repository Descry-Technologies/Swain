"""swain share — launch card + social copy for Twitter and LinkedIn."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from rich.console import Console
from rich.rule import Rule

from descry.commands.launch_card import (
    LaunchCardData,
    build_launch_card_data,
    run_launch_card,
)

console = Console()

_BADGE_COLORS = {
    "READY": "2fdd92",
    "BLOCKED": "ff5a5f",
    "REVIEW": "f0b429",
    "NO SCAN YET": "9aa4b2",
}


def run_share(repo_root: Path) -> None:
    profile_path = repo_root / ".swain" / "profile.yaml"
    if not profile_path.exists():
        console.print(
            "[yellow]No .swain/profile.yaml found. "
            "Run [bold]swain scan[/bold] first.[/yellow]"
        )
        return

    with console.status("[dim]Writing launch card…[/dim]"):
        ok = run_launch_card(repo_root)
    if not ok:
        return

    data = build_launch_card_data(repo_root)
    card_path = repo_root / "swain-launch-card.svg"

    tweet = _tweet(data)
    linkedin = _linkedin(data)
    badge_md = badge_markdown(data)

    def _block(text: str) -> None:
        for line in text.splitlines():
            console.print(("  " + line) if line else "")

    console.print()
    console.print(Rule("[bold]Twitter / X[/bold]", style="#253040"))
    console.print()
    _block(tweet)
    console.print()
    console.print(Rule("[bold]LinkedIn[/bold]", style="#253040"))
    console.print()
    _block(linkedin)
    console.print()
    console.print(Rule("[bold]README badge[/bold]", style="#253040"))
    console.print()
    console.print(f"  [cyan]{badge_md}[/cyan]")
    console.print()

    copied = _to_clipboard(tweet)
    if copied:
        console.print("[green]✓[/green] Tweet text copied to clipboard")
    else:
        console.print("[dim]Copy the tweet text above[/dim]")

    console.print(f"\n[bold]Attach to post:[/bold] [cyan]{card_path}[/cyan]")


def _tweet(data: LaunchCardData) -> str:
    repo = data.repo_name

    if data.verdict == "READY":
        return (
            f"Scanned {repo} with Swain before shipping ✅\n"
            "\n"
            "0 blockers. Ship it.\n"
            "\n"
            "github.com/Descry-Technologies/Swain"
        )

    if data.verdict == "BLOCKED":
        top = data.top_issue_title
        if len(top) > 55:
            words, out = data.top_issue_title.split(), ""
            for w in words:
                candidate = f"{out} {w}".strip() if out else w
                if len(candidate) > 52:
                    break
                out = candidate
            top = out + "…"
        s = "s" if data.launch_blockers != 1 else ""
        return (
            f"My AI security lead blocked my {repo} launch 🚫\n"
            "\n"
            f"{data.launch_blockers} blocker{s} caught before prod:\n"
            f"→ {top}\n"
            "\n"
            "Fixing before I ship.\n"
            "\n"
            "github.com/Descry-Technologies/Swain"
        )

    s = "s" if data.open_findings != 1 else ""
    return (
        f"Swain flagged {data.open_findings} issue{s} in {repo} 👀\n"
        "\n"
        "Reviewing before launch.\n"
        "\n"
        "github.com/Descry-Technologies/Swain"
    )


def _linkedin(data: LaunchCardData) -> str:
    repo = data.repo_name
    stack = data.stack

    if data.verdict == "READY":
        return (
            f"Just ran my AI security lead on {repo} before shipping.\n"
            "\n"
            "0 findings. 0 blockers. Clean scan.\n"
            "\n"
            f"Stack: {stack}\n"
            "\n"
            "That's the goal — build fast, ship safe.\n"
            "\n"
            "Runs on your existing Claude/Codex subscriptions. No SaaS.\n"
            "\n"
            "Swain: github.com/Descry-Technologies/Swain"
        )

    if data.verdict == "BLOCKED":
        b = data.launch_blockers
        f = data.open_findings
        top = data.top_issue_title
        bs = "s" if b != 1 else ""
        fs = "s" if f != 1 else ""
        return (
            f"I was about to ship {repo}. My AI security lead stopped me.\n"
            "\n"
            f"Swain caught {f} issue{fs} — including: {top.lower()}.\n"
            "\n"
            f"{b} launch blocker{bs}. None were obvious from reading the code.\n"
            "\n"
            f"Stack: {stack}\n"
            "\n"
            "This is what shipping responsibly looks like.\n"
            "\n"
            "Swain: github.com/Descry-Technologies/Swain"
        )

    f = data.open_findings
    fs = "s" if f != 1 else ""
    return (
        f"Ran a security scan on {repo} before launch.\n"
        "\n"
        f"{f} issue{fs} flagged for review before I ship.\n"
        "\n"
        f"Stack: {stack}\n"
        "\n"
        "Swain: github.com/Descry-Technologies/Swain"
    )


def badge_markdown(data: LaunchCardData) -> str:
    color = _BADGE_COLORS.get(data.verdict, "9aa4b2")
    label = data.verdict.replace(" ", "%20")
    url = f"https://img.shields.io/badge/Swain-{label}-{color}?style=flat-square"
    return f"![Swain launch check]({url})"


def _to_clipboard(text: str) -> bool:
    if sys.platform == "darwin":
        candidates: list[list[str]] = [["pbcopy"]]
    elif sys.platform == "win32":
        candidates = [["clip"]]
    else:
        candidates = [
            ["wl-copy"],
            ["xclip", "-selection", "clipboard"],
            ["xsel", "--clipboard", "--input"],
        ]
    for cmd in candidates:
        try:
            result = subprocess.run(  # noqa: S603 - fixed command list.
                cmd,
                input=text.encode(),
                capture_output=True,
                timeout=5,
            )
            if result.returncode == 0:
                return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    return False
