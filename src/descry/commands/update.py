"""swain update - refresh a source-installed Swain command."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from rich.console import Console
from rich.panel import Panel

console = Console()


def run_update(
    *,
    source_dir: Path | None = None,
    bin_dir: Path | None = None,
    check_only: bool = False,
) -> bool:
    source = source_dir or _default_source_dir()
    if not (source / ".git").exists():
        console.print(
            Panel.fit(
                "[yellow]No managed Swain source checkout found.[/yellow]\n\n"
                "Install or update with:\n"
                "  curl -fsSL https://raw.githubusercontent.com/"
                "Descry-Technologies/Swain/main/install.sh | sh\n\n"
                f"Expected source: {source}",
                title="Swain Update",
            )
        )
        return False

    git = shutil.which("git")
    uv = shutil.which("uv")
    if git is None or uv is None:
        missing = "git" if git is None else "uv"
        console.print(f"[red]{missing} is required to update Swain.[/red]")
        return False

    console.print(
        Panel.fit("[bold cyan]Updating Swain[/bold cyan]", subtitle=str(source))
    )
    fetch = _run([git, "-C", str(source), "fetch", "--prune"])
    if fetch.returncode != 0:
        _print_failure(fetch)
        return False

    behind = _run([git, "-C", str(source), "rev-list", "--count", "HEAD..@{u}"])
    ahead = _run([git, "-C", str(source), "rev-list", "--count", "@{u}..HEAD"])
    if behind.returncode != 0 or ahead.returncode != 0:
        console.print(
            "[yellow]Could not compare with upstream. Running `git pull` "
            "directly.[/yellow]"
        )
    else:
        console.print(
            f"[dim]Upstream delta: {behind.stdout.strip() or '0'} new, "
            f"{ahead.stdout.strip() or '0'} local[/dim]"
        )
        if check_only:
            return True

    pull = _run([git, "-C", str(source), "pull", "--ff-only"])
    if pull.returncode != 0:
        _print_failure(pull)
        return False

    install_env = dict(os.environ)
    target_bin = bin_dir or _default_bin_dir()
    if target_bin:
        target_bin.mkdir(parents=True, exist_ok=True)
        install_env["UV_TOOL_BIN_DIR"] = str(target_bin)
    install = _run(
        [uv, "tool", "install", "--force", str(source)],
        env=install_env,
    )
    if install.returncode != 0:
        _print_failure(install)
        return False

    console.print(
        Panel.fit(
            "[bold green]Swain is up to date.[/bold green]\n\n"
            "Run `swain version` to confirm the installed command.",
            title="Done",
        )
    )
    return True


def _default_source_dir() -> Path:
    configured = os.environ.get("SWAIN_SOURCE_DIR")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".swain" / "source"


def _default_bin_dir() -> Path | None:
    configured = os.environ.get("SWAIN_BIN_DIR")
    if configured:
        return Path(configured).expanduser()
    installed = shutil.which("swain")
    if installed:
        path = Path(installed).resolve()
        if ".venv" not in path.parts:
            return path.parent
    return Path.home() / ".local" / "bin"


def _run(
    cmd: list[str],
    *,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        cmd,
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )


def _print_failure(result: subprocess.CompletedProcess[str]) -> None:
    console.print(f"[red]Command failed: {' '.join(result.args)}[/red]")
    output = (result.stdout + result.stderr).strip()
    if output:
        console.print(f"[dim]{output[-1200:]}[/dim]")
