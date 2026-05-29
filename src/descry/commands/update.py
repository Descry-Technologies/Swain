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
        [
            uv,
            "tool",
            "install",
            "--force",
            "--reinstall-package",
            "swain",
            str(source),
        ],
        env=install_env,
    )
    if install.returncode != 0:
        _print_failure(install)
        return False

    command_path = target_bin / "swain"
    if not command_path.exists():
        console.print(
            Panel.fit(
                "[red]Swain updated, but the command shim was not created.[/red]\n\n"
                f"Expected command: {command_path}\n\n"
                "Run the installer again or choose an explicit bin dir:\n"
                f"  SWAIN_BIN_DIR={target_bin} "
                "curl -fsSL https://raw.githubusercontent.com/"
                "Descry-Technologies/Swain/main/install.sh | sh",
                title="Update Failed",
            )
        )
        return False

    path_hint = ""
    if not _path_contains(target_bin):
        path_hint = (
            "\n\n[yellow]That directory is not on PATH in this shell.[/yellow]\n"
            f"Run now: `{command_path}`\n"
            f"Add later: `export PATH=\"{target_bin}:$PATH\"`"
        )

    console.print(
        Panel.fit(
            "[bold green]Swain is up to date.[/bold green]\n\n"
            f"Installed command: {command_path}\n"
            "Run `swain version` to confirm the installed command."
            f"{path_hint}",
            title="Done",
        )
    )
    return True


def _default_source_dir() -> Path:
    configured = os.environ.get("SWAIN_SOURCE_DIR")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".swain" / "source"


def _default_bin_dir() -> Path:
    configured = os.environ.get("SWAIN_BIN_DIR")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".local" / "bin"


def _path_contains(path: Path) -> bool:
    target = str(path.expanduser().resolve())
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        if not entry:
            continue
        try:
            if str(Path(entry).expanduser().resolve()) == target:
                return True
        except OSError:
            continue
    return False


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
