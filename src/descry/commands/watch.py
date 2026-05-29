"""Foreground git watcher for Swain scheduled recon."""

from __future__ import annotations

import asyncio
import hashlib
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from rich.console import Console

from descry.memory.coworker import CoworkerMemory
from descry.memory.store import MemoryStore
from descry.orchestrator.lead import LeadOrchestrationError, LeadOrchestrator

console = Console()


@dataclass(frozen=True)
class GitWatchState:
    commit: str
    tracked_status: str
    signature: str
    valid: bool = True
    error: str = ""


@dataclass(frozen=True)
class WatchPollResult:
    triggered: bool
    reason: str
    signature: str
    mission_id: str = ""


async def run_watch(
    repo_root: Path,
    *,
    interval_s: int = 30,
    once: bool = False,
    mock: bool = False,
) -> None:
    if not (repo_root / ".swain" / "profile.yaml").exists():
        console.print(
            "[yellow]No .swain/profile.yaml found. "
            "Run [bold]swain setup[/bold] before watching this repo.[/yellow]"
        )
        return

    store = MemoryStore(repo_root)
    coworker = CoworkerMemory(store)
    state = coworker.load_watch_state()
    state.enabled = True
    state.repo_path = str(repo_root)
    state.interval_s = interval_s
    state.pid = os.getpid()
    coworker.save_watch_state(state)

    console.print(
        f"[cyan]Watching {repo_root}[/cyan] "
        f"[dim](git polling every {interval_s}s)[/dim]"
    )
    while True:
        result = await poll_git_once(repo_root, mock=mock)
        if result.triggered:
            console.print(f"[green]Triggered recon:[/green] {result.reason}")
        elif once and not result.signature:
            console.print(f"[yellow]Watch unavailable:[/yellow] {result.reason}")
        elif once:
            console.print(f"[dim]No git change: {result.signature[:12]}[/dim]")
        if once:
            return
        await asyncio.sleep(interval_s)


async def poll_git_once(repo_root: Path, *, mock: bool = False) -> WatchPollResult:
    git_state = read_git_state(repo_root)
    store = MemoryStore(repo_root)
    coworker = CoworkerMemory(store)
    watch_state = coworker.load_watch_state()
    previous_signature = watch_state.last_git_signature

    if not git_state.valid:
        watch_state.enabled = False
        watch_state.repo_path = str(repo_root)
        watch_state.last_trigger_reason = git_state.error
        coworker.save_watch_state(watch_state)
        return WatchPollResult(
            triggered=False,
            reason=git_state.error,
            signature="",
        )

    watch_state.enabled = True
    watch_state.repo_path = str(repo_root)
    watch_state.last_git_signature = git_state.signature

    if not previous_signature:
        coworker.save_watch_state(watch_state)
        return WatchPollResult(
            triggered=False,
            reason="recorded initial git state",
            signature=git_state.signature,
        )

    if previous_signature == git_state.signature:
        coworker.save_watch_state(watch_state)
        return WatchPollResult(
            triggered=False,
            reason="git state unchanged",
            signature=git_state.signature,
        )

    reason = _change_reason(previous_signature, git_state)
    watch_state.last_triggered_at = _utc_now()
    watch_state.last_trigger_reason = reason
    coworker.save_watch_state(watch_state)

    mission_id = ""
    if (repo_root / ".swain" / "profile.yaml").exists():
        try:
            result = await LeadOrchestrator(repo_root).run_recon(
                trigger="on_commit",
                objective=f"watch-triggered recon: {reason}",
                mock=mock,
                persist=not mock,
            )
            mission_id = result.mission_id
            watch_state.last_scan_mission_id = mission_id
            coworker.save_watch_state(watch_state)
        except LeadOrchestrationError:
            mission_id = ""

    return WatchPollResult(
        triggered=True,
        reason=reason,
        signature=git_state.signature,
        mission_id=mission_id,
    )


def read_git_state(repo_root: Path) -> GitWatchState:
    is_inside = _git_output(repo_root, "rev-parse", "--is-inside-work-tree")
    if is_inside != "true":
        return GitWatchState(
            commit="",
            tracked_status="",
            signature="",
            valid=False,
            error="not a git repository",
        )
    commit = _git_output(repo_root, "rev-parse", "HEAD")
    if not commit:
        return GitWatchState(
            commit="",
            tracked_status="",
            signature="",
            valid=False,
            error="git HEAD is unavailable",
        )
    status = _git_output(
        repo_root,
        "status",
        "--porcelain",
        "--untracked-files=no",
    )
    payload = f"{commit}\n{status}"
    signature = hashlib.sha256(payload.encode()).hexdigest()
    return GitWatchState(commit=commit, tracked_status=status, signature=signature)


def _git_output(repo_root: Path, *args: str) -> str:
    git_path = shutil.which("git")
    if not git_path:
        return ""
    try:
        proc = subprocess.run(  # noqa: S603
            [git_path, *args],
            cwd=repo_root,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if proc.returncode != 0:
        return ""
    return proc.stdout.strip()


def _change_reason(previous_signature: str, git_state: GitWatchState) -> str:
    status_note = (
        "tracked files changed" if git_state.tracked_status else "commit changed"
    )
    return f"{status_note}; state {previous_signature[:8]} -> {git_state.signature[:8]}"


def _utc_now() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()
