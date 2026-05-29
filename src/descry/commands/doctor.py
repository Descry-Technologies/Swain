"""swain doctor — preflight checks before a scan."""

from __future__ import annotations

import asyncio
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from descry.playbooks.loader import PlaybookLoader
from descry.resources import builtin_playbooks_dir
from descry.scanners.inventory import RepoInventory

console = Console()


@dataclass(frozen=True)
class DoctorCheck:
    name: str
    status: str
    detail: str
    next_step: str = ""


async def run_doctor(repo_root: Path, probe_workers: bool = True) -> bool:
    checks = await collect_checks(repo_root, probe_workers=probe_workers)
    _render_checks(repo_root, checks)
    return not any(check.status == "error" for check in checks)


async def collect_checks(
    repo_root: Path,
    *,
    probe_workers: bool = True,
) -> list[DoctorCheck]:
    checks = [
        _check_repo(repo_root),
        _check_profile(repo_root),
        _check_playbooks(repo_root),
        _check_generated_artifacts(repo_root),
    ]
    checks.extend(await _check_workers(probe_workers=probe_workers))
    return checks


def _check_repo(repo_root: Path) -> DoctorCheck:
    if not repo_root.exists():
        return DoctorCheck(
            "repo",
            "error",
            f"{repo_root} does not exist",
            "Pass an existing project path.",
        )
    if not repo_root.is_dir():
        return DoctorCheck(
            "repo",
            "error",
            f"{repo_root} is not a directory",
            "Pass the repository directory, not a file.",
        )
    return DoctorCheck("repo", "ok", str(repo_root.resolve()))


def _check_profile(repo_root: Path) -> DoctorCheck:
    profile_path = repo_root / ".swain" / "profile.yaml"
    if profile_path.exists():
        return DoctorCheck("profile", "ok", ".swain/profile.yaml found")
    return DoctorCheck(
        "profile",
        "warn",
        "No .swain/profile.yaml yet",
        "Run `swain init` or start with `/scan` in the TUI.",
    )


def _check_playbooks(repo_root: Path) -> DoctorCheck:
    try:
        inventory = RepoInventory.scan(repo_root)
        loader = PlaybookLoader(
            builtin_dir=builtin_playbooks_dir(),
            user_dir=repo_root / ".swain" / "playbooks",
        )
        playbooks = loader.load_all()
        applicable = loader.filter_applicable(playbooks, inventory)
    except Exception as exc:
        return DoctorCheck(
            "playbooks",
            "error",
            f"Could not load playbooks: {exc}",
            "Fix invalid YAML/schema errors before scanning.",
        )

    if not playbooks:
        return DoctorCheck(
            "playbooks",
            "error",
            "No playbooks found",
            "Reinstall Swain or restore the bundled playbooks directory.",
        )
    if not applicable:
        return DoctorCheck(
            "playbooks",
            "warn",
            f"{len(playbooks)} loaded, none matched this repo",
            "Run `swain init --no-llm` and check the inferred stack.",
        )
    return DoctorCheck(
        "playbooks",
        "ok",
        f"{len(applicable)} applicable of {len(playbooks)} loaded",
    )


async def _check_workers(*, probe_workers: bool) -> list[DoctorCheck]:
    worker_specs = [
        ("claude", ["claude", "--output-format", "text", "-p", "Reply OK"]),
        (
            "codex",
            [
                "codex",
                "exec",
                "--skip-git-repo-check",
                "-s",
                "read-only",
                "Reply OK",
            ],
        ),
    ]

    checks: list[DoctorCheck] = []
    for name, probe_cmd in worker_specs:
        checks.append(await _check_worker(name, probe_cmd, probe_workers))
    return checks


async def _check_worker(
    name: str,
    probe_cmd: list[str],
    probe_workers: bool,
) -> DoctorCheck:
    path = shutil.which(name)
    if path is None:
        return DoctorCheck(
            name,
            "warn",
            f"{name} CLI not found",
            f"Install and authenticate {name}, or expect fallback/mock behavior.",
        )
    if not probe_workers:
        return DoctorCheck(
            name,
            "ok",
            f"{path} found; probe skipped",
            "Run `swain doctor --probe-workers` to check auth/quota.",
        )

    result = await _probe_command(probe_cmd)
    if result[0]:
        return DoctorCheck(name, "ok", f"{path} found and responded")

    diagnostic = result[1] or "probe failed"
    status = "warn"
    next_step = f"Open `{name}` once and finish auth, then rerun doctor."
    if "limit" in diagnostic.lower() or "quota" in diagnostic.lower():
        next_step = "Wait for quota reset or let scans fall back to the other worker."
    return DoctorCheck(name, status, diagnostic[:180], next_step)


async def _probe_command(cmd: list[str]) -> tuple[bool, str]:
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=20)
    except TimeoutError:
        return False, "probe timed out"
    except FileNotFoundError as exc:
        return False, str(exc)

    output = (stdout + stderr).decode("utf-8", errors="replace").strip()
    return proc.returncode == 0, _first_line(output)


def _check_generated_artifacts(repo_root: Path) -> DoctorCheck:
    tracked = _tracked_generated_files(repo_root)
    if tracked is None:
        return DoctorCheck("package hygiene", "ok", "not a git repo; skipped")
    if tracked:
        sample = ", ".join(tracked[:3])
        suffix = "..." if len(tracked) > 3 else ""
        return DoctorCheck(
            "package hygiene",
            "warn",
            f"{len(tracked)} generated file(s) tracked: {sample}{suffix}",
            "Stop tracking __pycache__ and *.pyc before release.",
        )
    return DoctorCheck("package hygiene", "ok", "no tracked Python bytecode")


def _tracked_generated_files(repo_root: Path) -> list[str] | None:
    git = shutil.which("git")
    if git is None:
        return None
    try:
        proc = subprocess.run(  # noqa: S603
            [git, "-C", str(repo_root), "ls-files"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return [
        path for path in proc.stdout.splitlines()
        if _is_generated_artifact(path)
    ]


def _is_generated_artifact(path: str) -> bool:
    parts = path.split("/")
    return "__pycache__" in parts or path.endswith((".pyc", ".pyo"))


def _render_checks(repo_root: Path, checks: list[DoctorCheck]) -> None:
    console.print(
        Panel.fit("[bold cyan]Swain Doctor[/bold cyan]", subtitle=str(repo_root))
    )

    table = Table(show_header=True, header_style="bold")
    table.add_column("Check", width=18)
    table.add_column("Status", width=8)
    table.add_column("Detail")
    table.add_column("Next step")

    for check in checks:
        table.add_row(
            check.name,
            _status_label(check.status),
            check.detail,
            check.next_step,
        )
    console.print(table)

    errors = [check for check in checks if check.status == "error"]
    warnings = [check for check in checks if check.status == "warn"]
    if errors:
        console.print("\n[red]Not ready. Fix the errors above before scanning.[/red]")
    elif warnings:
        console.print("\n[yellow]Usable, but fix the warnings before release.[/yellow]")
    else:
        console.print("\n[green]Ready to scan.[/green]")


def _status_label(status: str) -> str:
    if status == "ok":
        return "[green]ok[/green]"
    if status == "warn":
        return "[yellow]warn[/yellow]"
    if status == "error":
        return "[red]error[/red]"
    return status


def _first_line(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""
