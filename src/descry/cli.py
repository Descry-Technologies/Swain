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
daemon_app = typer.Typer(help="Install and control Swain's user daemon.")

_COMMAND_NAMES = {
    "init",
    "scan",
    "feedback",
    "fix",
    "launch-card",
    "share",
    "badge",
    "status",
    "doctor",
    "demo",
    "daemon",
    "setup",
    "update",
    "version",
    "watch",
}

app.add_typer(daemon_app, name="daemon")


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

            repo = _get_repo_root(first_arg)
            _maybe_run_first_launch_setup(repo)
            SwainApp(repo_path=repo).run()
            return
    app()


@app.callback(invoke_without_command=True)
def default(ctx: typer.Context) -> None:
    """Open the interactive TUI. Run `swain /path` to pre-load a project."""
    if ctx.invoked_subcommand is not None:
        return
    from descry.tui.app import SwainApp

    repo = _get_repo_root(None)
    _maybe_run_first_launch_setup(repo)
    SwainApp(repo_path=repo).run()


def _maybe_run_first_launch_setup(repo: Path) -> None:
    from descry.commands.setup import run_setup, setup_completed

    if setup_completed(repo):
        return
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        rprint(
            "[yellow]Swain setup has not run for this repo yet. "
            f"Run `swain setup {repo}` before opening the TUI.[/yellow]"
        )
        return
    try:
        asyncio.run(run_setup(repo))
    except KeyboardInterrupt:
        raise typer.Exit(130) from None


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
def setup(
    path: str = typer.Argument(None, help="Repo path (defaults to current directory)"),
    mode: str = typer.Option(
        None,
        "--mode",
        help="Worker mode: hybrid, claude, or codex",
    ),
    claude_model: str = typer.Option(
        None,
        "--claude-model",
        help="Claude model id, or 'default' for the Claude CLI default",
    ),
    claude_runtime: str = typer.Option(
        None,
        "--claude-runtime",
        help="Claude runtime: cli or api",
    ),
    codex_model: str = typer.Option(
        None,
        "--codex-model",
        help="Codex model id, or 'default' for the Codex CLI default",
    ),
    codex_runtime: str = typer.Option(
        None,
        "--codex-runtime",
        help="Codex runtime: cli or api",
    ),
    speed: str = typer.Option(
        None,
        "--speed",
        help="Scan speed: careful, balanced, or fast",
    ),
    cli_task_timeout: int = typer.Option(
        None,
        "--cli-task-timeout",
        help=(
            "Seconds before a Claude/Codex CLI worker task is timed out; "
            "0 disables the wall-clock timeout"
        ),
    ),
    api_max_output_tokens: int = typer.Option(
        None,
        "--api-max-output-tokens",
        help="Maximum direct API output tokens per worker call",
    ),
    api_file_char_limit: int = typer.Option(
        None,
        "--api-file-char-limit",
        help="Maximum selected source characters included in direct API prompts",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Use defaults for unanswered setup choices",
    ),
    no_profile: bool = typer.Option(
        False,
        "--no-profile",
        help="Do not build the local project profile during setup",
    ),
) -> None:
    """Explain Swain and configure Claude/Codex workers for this repo."""
    from descry.commands.setup import run_setup

    try:
        asyncio.run(
            run_setup(
                _get_repo_root(path),
                worker_mode=mode,
                claude_model=claude_model,
                codex_model=codex_model,
                claude_runtime=claude_runtime,
                codex_runtime=codex_runtime,
                concurrency=speed,
                cli_task_timeout_s=cli_task_timeout,
                api_max_output_tokens=api_max_output_tokens,
                api_file_char_limit=api_file_char_limit,
                interactive=not yes,
                init_profile=not no_profile,
            )
        )
    except ValueError as exc:
        typer.echo(f"Setup failed: {exc}", err=True)
        raise typer.Exit(1) from None


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
def launch_card(
    path: str = typer.Argument(None, help="Repo path"),
    path_opt: str = typer.Option(
        None,
        "--path",
        "-p",
        help="Repo path (alternative to positional argument).",
        hidden=False,
    ),
    out: str = typer.Option(
        None,
        "--out",
        "-o",
        help="Output SVG path (defaults to <repo>/swain-launch-card.svg).",
    ),
) -> None:
    """Generate a shareable launch-readiness SVG from the latest scan."""
    from descry.commands.launch_card import run_launch_card

    ok = run_launch_card(
        _get_repo_root(path_opt or path),
        out_path=Path(out).resolve() if out else None,
    )
    if not ok:
        raise typer.Exit(1)


@app.command()
def status(
    path: str = typer.Argument(None, help="Repo path"),
) -> None:
    """Show current security posture, learned conventions, and schedule."""
    from descry.commands.status import run_status

    asyncio.run(run_status(_get_repo_root(path)))


@app.command()
def watch(
    path: str = typer.Argument(None, help="Repo path"),
    interval: int = typer.Option(
        30,
        "--interval",
        "-i",
        help="Git polling interval in seconds.",
    ),
    once: bool = typer.Option(
        False,
        "--once",
        help="Poll once and exit. Useful for tests and diagnostics.",
    ),
    mock: bool = typer.Option(
        False,
        "--mock",
        help="Use mock worker when a change triggers recon.",
    ),
) -> None:
    """Watch git state and trigger scheduled recon when tracked files change."""
    from descry.commands.watch import run_watch

    asyncio.run(
        run_watch(
            _get_repo_root(path),
            interval_s=interval,
            once=once,
            mock=mock,
        )
    )


@daemon_app.command("install")
def daemon_install(
    path: str = typer.Argument(None, help="Repo path"),
    interval: int = typer.Option(
        30,
        "--interval",
        "-i",
        help="Git polling interval in seconds.",
    ),
) -> None:
    """Install a Linux systemd user service for `swain watch`."""
    from descry.commands.daemon import install_daemon

    install_daemon(_get_repo_root(path), interval_s=interval)


@daemon_app.command("start")
def daemon_start(path: str = typer.Argument(None, help="Repo path")) -> None:
    """Start the installed Swain watch service."""
    from descry.commands.daemon import start_daemon

    if not start_daemon(_get_repo_root(path)):
        raise typer.Exit(1)


@daemon_app.command("stop")
def daemon_stop(path: str = typer.Argument(None, help="Repo path")) -> None:
    """Stop the installed Swain watch service."""
    from descry.commands.daemon import stop_daemon

    if not stop_daemon(_get_repo_root(path)):
        raise typer.Exit(1)


@daemon_app.command("status")
def daemon_status_cmd(path: str = typer.Argument(None, help="Repo path")) -> None:
    """Show systemd and local watch state for this repo."""
    from descry.commands.daemon import daemon_status

    daemon_status(_get_repo_root(path))


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
def update(
    source_dir: str = typer.Option(
        None,
        "--source-dir",
        help="Managed Swain source checkout (defaults to ~/.swain/source)",
    ),
    bin_dir: str = typer.Option(
        None,
        "--bin-dir",
        help="Directory where the swain command should be installed",
    ),
    check: bool = typer.Option(
        False,
        "--check",
        help="Fetch and report upstream status without reinstalling",
    ),
) -> None:
    """Update a source-installed Swain command without PyPI."""
    from descry.commands.update import run_update

    ok = run_update(
        source_dir=Path(source_dir).expanduser() if source_dir else None,
        bin_dir=Path(bin_dir).expanduser() if bin_dir else None,
        check_only=check,
    )
    if not ok:
        raise typer.Exit(1)


@app.command()
def share(
    path: str = typer.Argument(None, help="Repo path (defaults to current directory)"),
    path_opt: str = typer.Option(
        None,
        "--path",
        "-p",
        help="Repo path (alternative to positional argument).",
    ),
) -> None:
    """Generate a launch card and social copy for Twitter and LinkedIn."""
    from descry.commands.share import run_share

    run_share(_get_repo_root(path_opt or path))


@app.command()
def badge(
    path: str = typer.Argument(None, help="Repo path (defaults to current directory)"),
    path_opt: str = typer.Option(
        None,
        "--path",
        "-p",
        help="Repo path (alternative to positional argument).",
    ),
) -> None:
    """Print a README badge for the current scan verdict."""
    from descry.commands.badge import run_badge

    run_badge(_get_repo_root(path_opt or path))


@app.command()
def version() -> None:
    """Show version."""
    from descry import __version__

    rprint(f"swain {__version__}")
