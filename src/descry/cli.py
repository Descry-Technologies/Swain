"""Swain CLI — `swain` alone opens the TUI; subcommands for non-interactive use."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import typer
from rich import print as rprint

# no_args_is_help=False so `swain` alone falls through to the TUI callback
app = typer.Typer(
    name="swain",
    help="Local AI security lead for your codebase.",
    no_args_is_help=False,
    invoke_without_command=True,
)

_COMMAND_NAMES = {
    "init",
    "scan",
    "feedback",
    "fix",
    "status",
    "doctor",
    "demo",
    "version",
}


def _get_repo_root(path: str | None) -> Path:
    root = Path(path) if path else Path.cwd()
    if not root.exists():
        typer.echo(f"Path not found: {root}", err=True)
        raise typer.Exit(1)
    return root.resolve()


def main() -> None:
    """CLI entry point with `swain /path` support before Typer dispatch."""
    if len(sys.argv) > 1:
        first_arg = sys.argv[1]
        if (
            not first_arg.startswith("-")
            and first_arg not in _COMMAND_NAMES
            and Path(first_arg).exists()
        ):
            from descry.tui.app import SwainApp

            SwainApp(repo_path=_get_repo_root(first_arg)).run()
            return
    app()


@app.callback(invoke_without_command=True)
def default(ctx: typer.Context) -> None:
    """Open the interactive TUI. Run `swain /path` to pre-load a project."""
    if ctx.invoked_subcommand is not None:
        return
    from descry.tui.app import SwainApp

    repo = _get_repo_root(None)
    SwainApp(repo_path=repo).run()


@app.command()
def init(
    path: str = typer.Argument(None, help="Repo path (defaults to current directory)"),
    no_llm: bool = typer.Option(
        False,
        "--no-llm",
        help="Skip LLM bootstrap, use static scan only",
    ),
) -> None:
    """Bootstrap Swain for a repository. Scans the repo and infers a threat model."""
    from descry.commands.init import run_init

    asyncio.run(run_init(_get_repo_root(path), use_llm=not no_llm))


@app.command()
def scan(
    path: str = typer.Argument(None, help="Repo path (defaults to current directory)"),
    trigger: str = typer.Option(
        "manual",
        "--trigger",
        "-t",
        help="Trigger type: manual, on_pr, on_commit, daily",
    ),
    output: str = typer.Option(
        "terminal",
        "--output",
        "-o",
        help="Output format: terminal, json, markdown",
    ),
    out_file: str = typer.Option(None, "--file", "-f", help="Write output to file"),
    mock: bool = typer.Option(
        False,
        "--mock",
        help="Use mock worker (offline/testing)",
    ),
) -> None:
    """Run a security scan against the repository."""
    from descry.commands.scan import run_scan

    asyncio.run(
        run_scan(
            _get_repo_root(path),
            trigger=trigger,
            output=output,
            out_file=out_file,
            mock=mock,
        )
    )


@app.command()
def feedback(
    finding_id: str = typer.Argument(..., help="Finding ID"),
    action: str = typer.Argument(..., help="Action: fp, fix, wontfix, snooze"),
    path: str = typer.Option(None, "--path", "-p", help="Repo path"),
    comment: str = typer.Option("", "--comment", "-c", help="Optional comment"),
) -> None:
    """Record feedback on a finding (fp=false positive, fix=fixed, wontfix, snooze)."""
    from descry.commands.feedback import run_feedback

    asyncio.run(
        run_feedback(
            _get_repo_root(path),
            finding_id=finding_id,
            action=action,
            comment=comment,
        )
    )


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
def doctor(
    path: str = typer.Argument(None, help="Repo path"),
    probe_workers: bool = typer.Option(
        True,
        "--probe-workers/--no-probe-workers",
        help="Send tiny prompts to Claude/Codex to check auth and quota.",
    ),
) -> None:
    """Check whether Swain is ready to scan this repo."""
    from descry.commands.doctor import run_doctor

    ready = asyncio.run(run_doctor(_get_repo_root(path), probe_workers=probe_workers))
    if not ready:
        raise typer.Exit(1)


@app.command()
def demo(
    reset: bool = typer.Option(
        True,
        "--reset/--keep",
        help="Reset the local demo copy before running.",
    ),
    tui: bool = typer.Option(
        False,
        "--tui",
        help="Open the demo TUI after the offline check.",
    ),
) -> None:
    """Run the public offline demo without Claude/Codex quota."""
    from descry.commands.demo import run_demo

    repo = asyncio.run(run_demo(reset=reset))
    if repo is None:
        raise typer.Exit(1)
    if tui:
        from descry.tui.app import SwainApp

        SwainApp(repo_path=repo).run()


@app.command()
def version() -> None:
    """Show version."""
    from descry import __version__

    rprint(f"swain {__version__}")
