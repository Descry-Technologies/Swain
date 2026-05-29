"""swain demo - run the public offline demo from any directory."""

from __future__ import annotations

import shutil
from pathlib import Path

from rich.console import Console
from rich.panel import Panel

from descry.commands.doctor import run_doctor
from descry.commands.scan import run_scan
from descry.commands.status import run_status
from descry.resources import bundled_demo_dir

console = Console()


def default_demo_workspace() -> Path:
    return Path.home() / ".swain" / "demo" / "launchpad-saas"


def prepare_demo_repo(
    destination: Path | None = None,
    *,
    reset: bool = True,
) -> Path:
    source = bundled_demo_dir()
    target = destination or default_demo_workspace()

    if reset and target.exists():
        shutil.rmtree(target)
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, target, ignore=_ignore_demo_artifacts)
    return target


async def run_demo(
    *,
    reset: bool = True,
    destination: Path | None = None,
) -> Path | None:
    repo_root = prepare_demo_repo(destination, reset=reset)
    console.print(
        Panel.fit(
            "[bold cyan]Swain Demo[/bold cyan]\n"
            "Offline launch-risk demo. No Claude/Codex quota is used.",
            subtitle=str(repo_root),
        )
    )

    ready = await run_doctor(repo_root, probe_workers=False)
    if not ready:
        return None
    await run_status(repo_root)
    await run_scan(repo_root, output="markdown", mock=True)
    console.print(f"\n[bold]Open the TUI[/bold]: [cyan]swain {repo_root}[/cyan]")
    return repo_root


def _ignore_demo_artifacts(directory: str, names: list[str]) -> set[str]:
    ignored = {"__pycache__", ".pytest_cache", "node_modules", ".venv"}
    if Path(directory).name == ".swain":
        ignored.add(".local")
    return ignored.intersection(names)
