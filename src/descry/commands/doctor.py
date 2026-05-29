"""swain doctor — preflight checks before a scan."""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import httpx
import yaml
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from descry.memory.config import SwainConfig
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
        _check_setup(repo_root),
        _check_profile(repo_root),
        _check_playbooks(repo_root),
        _check_generated_artifacts(repo_root),
    ]
    checks.extend(await _check_workers(repo_root, probe_workers=probe_workers))
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


def _check_setup(repo_root: Path) -> DoctorCheck:
    config_path = repo_root / ".swain" / "config.yaml"
    if not config_path.exists():
        return DoctorCheck(
            "setup",
            "warn",
            "No .swain/config.yaml yet",
            "Run `swain setup` to choose Claude/Codex workers and model settings.",
        )
    try:
        data = yaml.safe_load(config_path.read_text()) or {}
        config = SwainConfig.from_dict(data)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        return DoctorCheck(
            "setup",
            "error",
            f"Invalid .swain/config.yaml: {exc}",
            "Run `swain setup` again.",
        )
    if not config.setup_completed:
        return DoctorCheck(
            "setup",
            "warn",
            ".swain/config.yaml exists but setup is incomplete",
            "Run `swain setup` again.",
        )
    return DoctorCheck("setup", "ok", config.worker_summary())


def _check_profile(repo_root: Path) -> DoctorCheck:
    profile_path = repo_root / ".swain" / "profile.yaml"
    if profile_path.exists():
        return DoctorCheck("profile", "ok", ".swain/profile.yaml found")
    return DoctorCheck(
        "profile",
        "warn",
        "No .swain/profile.yaml yet",
        "Run `swain setup` or start with `/scan` in the TUI.",
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


async def _check_workers(repo_root: Path, *, probe_workers: bool) -> list[DoctorCheck]:
    config = _load_config_or_default(repo_root)
    checks: list[DoctorCheck] = []
    if config.uses_claude:
        if config.claude_runtime == "api":
            checks.append(
                await _check_anthropic_api(config, probe_workers=probe_workers)
            )
        else:
            checks.append(
                await _check_worker(
                    "claude",
                    ["claude", "--output-format", "text", "-p", "Reply OK"],
                    probe_workers,
                )
            )
    if config.uses_codex:
        if config.codex_runtime == "api":
            checks.append(await _check_openai_api(config, probe_workers=probe_workers))
        else:
            checks.append(
                await _check_worker(
                    "codex",
                    [
                        "codex",
                        "exec",
                        "--skip-git-repo-check",
                        "-s",
                        "read-only",
                        "Reply OK",
                    ],
                    probe_workers,
                )
            )
    return checks


def _load_config_or_default(repo_root: Path) -> SwainConfig:
    config_path = repo_root / ".swain" / "config.yaml"
    if not config_path.exists():
        return SwainConfig()
    try:
        return SwainConfig.from_dict(yaml.safe_load(config_path.read_text()) or {})
    except (OSError, ValueError, yaml.YAMLError):
        return SwainConfig()


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


async def _check_anthropic_api(
    config: SwainConfig,
    *,
    probe_workers: bool,
) -> DoctorCheck:
    if not config.claude_model:
        return DoctorCheck(
            "claude api",
            "warn",
            "Claude API runtime selected but no model is configured",
            "Run `swain setup` and enter an Anthropic model id.",
        )
    key = os.environ.get(config.claude_api_key_env)
    if not key:
        return DoctorCheck(
            "claude api",
            "warn",
            f"{config.claude_api_key_env} is not set",
            f"Export `{config.claude_api_key_env}` or switch Claude back to CLI.",
        )
    if not probe_workers:
        return DoctorCheck(
            "claude api",
            "ok",
            f"{config.claude_model}; key env present; probe skipped",
            "Run `swain doctor --probe-workers` to check auth/quota.",
        )
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                f"{config.claude_api_base_url}/v1/messages",
                headers={
                    "x-api-key": key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": config.claude_model,
                    "max_tokens": 8,
                    "messages": [{"role": "user", "content": "Reply OK"}],
                },
            )
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        return DoctorCheck(
            "claude api",
            "warn",
            f"HTTP {exc.response.status_code}: {exc.response.text[:140]}",
            "Check Anthropic API auth, model id, quota, and rate limits.",
        )
    except httpx.HTTPError as exc:
        return DoctorCheck(
            "claude api",
            "warn",
            str(exc)[:180],
            "Check network access and Anthropic API settings.",
        )
    return DoctorCheck("claude api", "ok", f"{config.claude_model} responded")


async def _check_openai_api(
    config: SwainConfig,
    *,
    probe_workers: bool,
) -> DoctorCheck:
    if not config.codex_model:
        return DoctorCheck(
            "codex api",
            "warn",
            "Codex API runtime selected but no model is configured",
            "Run `swain setup` and enter an OpenAI model id.",
        )
    key = os.environ.get(config.codex_api_key_env)
    if not key:
        return DoctorCheck(
            "codex api",
            "warn",
            f"{config.codex_api_key_env} is not set",
            f"Export `{config.codex_api_key_env}` or switch Codex back to CLI.",
        )
    if not probe_workers:
        return DoctorCheck(
            "codex api",
            "ok",
            f"{config.codex_model}; key env present; probe skipped",
            "Run `swain doctor --probe-workers` to check auth/quota.",
        )
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                f"{config.codex_api_base_url}/responses",
                headers={
                    "Authorization": f"Bearer {key}",
                    "content-type": "application/json",
                },
                json={
                    "model": config.codex_model,
                    "input": "Reply OK",
                    "max_output_tokens": 8,
                    "store": False,
                },
            )
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        return DoctorCheck(
            "codex api",
            "warn",
            f"HTTP {exc.response.status_code}: {exc.response.text[:140]}",
            "Check OpenAI API auth, model id, quota, and rate limits.",
        )
    except httpx.HTTPError as exc:
        return DoctorCheck(
            "codex api",
            "warn",
            str(exc)[:180],
            "Check network access and OpenAI API settings.",
        )
    return DoctorCheck("codex api", "ok", f"{config.codex_model} responded")


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
