"""Descry CLI — `descry` alone opens the TUI; subcommands for non-interactive use."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import typer
from rich import print as rprint

# no_args_is_help=False so `descry` alone falls through to the TUI callback
app = typer.Typer(
    name="descry",
    help="Autonomous AI security lead for your codebase.",
    no_args_is_help=False,
    invoke_without_command=True,
)


def _get_repo_root(path: str | None) -> Path:
    root = Path(path) if path else Path.cwd()
    if not root.exists():
        typer.echo(f"Path not found: {root}", err=True)
        raise typer.Exit(1)
    return root.resolve()


@app.callback(invoke_without_command=True)
def default(
    ctx: typer.Context,
    path: str = typer.Argument(None, help="Repo path — opens TUI for that project"),
) -> None:
    """Open the interactive TUI. Pass a repo path to pre-load a project."""
    if ctx.invoked_subcommand is not None:
        return
    from descry.tui.app import DescryApp
    repo = _get_repo_root(path)
    DescryApp(repo_path=repo).run()


@app.command()
def init(
    path: str = typer.Argument(None, help="Repo path (defaults to current directory)"),
    no_llm: bool = typer.Option(False, "--no-llm", help="Skip LLM bootstrap, use static scan only"),
) -> None:
    """Bootstrap Descry for a repository. Scans the repo and infers a threat model."""
    from descry.commands.init import run_init
    asyncio.run(run_init(_get_repo_root(path), use_llm=not no_llm))


@app.command()
def scan(
    path: str = typer.Argument(None, help="Repo path (defaults to current directory)"),
    trigger: str = typer.Option("manual", "--trigger", "-t", help="Trigger type: manual, on_pr, on_commit, daily"),
    output: str = typer.Option("terminal", "--output", "-o", help="Output format: terminal, json, markdown"),
    out_file: str = typer.Option(None, "--file", "-f", help="Write output to file"),
    mock: bool = typer.Option(False, "--mock", help="Use mock worker (offline/testing)"),
) -> None:
    """Run a security scan against the repository."""
    from descry.commands.scan import run_scan
    asyncio.run(run_scan(_get_repo_root(path), trigger=trigger, output=output, out_file=out_file, mock=mock))


@app.command()
def feedback(
    finding_id: str = typer.Argument(..., help="Finding ID"),
    action: str = typer.Argument(..., help="Action: fp, fix, wontfix, snooze"),
    path: str = typer.Option(None, "--path", "-p", help="Repo path"),
    comment: str = typer.Option("", "--comment", "-c", help="Optional comment"),
) -> None:
    """Record feedback on a finding (fp=false positive, fix=fixed, wontfix, snooze)."""
    from descry.commands.feedback import run_feedback
    asyncio.run(run_feedback(_get_repo_root(path), finding_id=finding_id, action=action, comment=comment))


@app.command()
def fix(
    finding_id: str = typer.Argument(..., help="Finding ID"),
    path: str = typer.Option(None, "--path", "-p", help="Repo path"),
) -> None:
    """Generate a Codex patch suggestion for a finding without applying it."""
    from descry.commands.fix import run_fix
    asyncio.run(run_fix(_get_repo_root(path), finding_id=finding_id))


@app.command()
def status(
    path: str = typer.Argument(None, help="Repo path"),
) -> None:
    """Show current security posture, learned conventions, and schedule."""
    from descry.commands.status import run_status
    asyncio.run(run_status(_get_repo_root(path)))


@app.command()
def version() -> None:
    """Show version."""
    from descry import __version__
    rprint(f"descry {__version__}")
