"""Linux systemd user-service helpers for Swain watch."""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
from pathlib import Path

from rich.console import Console

from descry.memory.coworker import CoworkerMemory
from descry.memory.store import MemoryStore
from descry.orchestrator.lead import LeadOrchestrator

console = Console()


def install_daemon(repo_root: Path, *, interval_s: int = 30) -> Path:
    service_name = service_name_for_repo(repo_root)
    service_path = systemd_user_dir() / service_name
    service_path.parent.mkdir(parents=True, exist_ok=True)
    swain_path = swain_command_path()
    service_path.write_text(render_systemd_service(repo_root, swain_path, interval_s))

    store = MemoryStore(repo_root)
    coworker = CoworkerMemory(store)
    state = LeadOrchestrator(repo_root).enable_watch(
        interval_s=interval_s,
        service_name=service_name,
    )
    state.installed_service_path = str(service_path)
    coworker.save_watch_state(state)

    _systemctl("daemon-reload")
    console.print(f"[green]Installed[/green] {service_path}")
    console.print(f"[dim]Start with: swain daemon start {repo_root}[/dim]")
    return service_path


def start_daemon(repo_root: Path) -> bool:
    return _control_daemon(repo_root, "start")


def stop_daemon(repo_root: Path) -> bool:
    return _control_daemon(repo_root, "stop")


def daemon_status(repo_root: Path) -> bool:
    service_name = service_name_for_repo(repo_root)
    store = MemoryStore(repo_root)
    state = CoworkerMemory(store).load_watch_state()
    console.print(f"[bold]Service[/bold]: {service_name}")
    console.print(f"[bold]Repo[/bold]: {repo_root}")
    console.print(
        f"[bold]Last trigger[/bold]: {state.last_triggered_at or 'never'} "
        f"{state.last_trigger_reason}"
    )
    proc = _systemctl("status", service_name, "--no-pager")
    if proc.stdout:
        console.print(proc.stdout.strip())
    if proc.stderr:
        console.print(f"[yellow]{proc.stderr.strip()}[/yellow]")
    return proc.returncode == 0


def render_systemd_service(
    repo_root: Path,
    swain_path: str,
    interval_s: int = 30,
) -> str:
    exec_start = (
        f"{_systemd_quote(swain_path)} watch {_systemd_quote(repo_root)} "
        f"--interval {interval_s}"
    )
    return f"""\
[Unit]
Description=Swain watch for {repo_root}
After=default.target

[Service]
Type=simple
WorkingDirectory={_systemd_quote(repo_root)}
ExecStart={exec_start}
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
"""


def service_name_for_repo(repo_root: Path) -> str:
    resolved = str(repo_root.resolve())
    digest = hashlib.sha256(resolved.encode()).hexdigest()[:10]
    name = re.sub(r"[^A-Za-z0-9_.-]+", "-", repo_root.name) or "repo"
    return f"swain-watch-{name}-{digest}.service"


def systemd_user_dir() -> Path:
    return Path.home() / ".config" / "systemd" / "user"


def swain_command_path() -> str:
    return shutil.which("swain") or "swain"


def _control_daemon(repo_root: Path, action: str) -> bool:
    service_name = service_name_for_repo(repo_root)
    proc = _systemctl(action, service_name)
    if proc.returncode == 0:
        label = "stopped" if action == "stop" else "started"
        console.print(f"[green]{label}[/green] {service_name}")
        return True
    console.print(f"[yellow]systemctl {action} failed for {service_name}[/yellow]")
    if proc.stderr:
        console.print(f"[dim]{proc.stderr.strip()}[/dim]")
    return False


def _systemctl(*args: str) -> subprocess.CompletedProcess[str]:
    systemctl_path = shutil.which("systemctl")
    if not systemctl_path:
        return subprocess.CompletedProcess(
            args=["systemctl", "--user", *args],
            returncode=1,
            stdout="",
            stderr="systemctl not found",
        )
    try:
        return subprocess.run(  # noqa: S603
            [systemctl_path, "--user", *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess(
            args=["systemctl", "--user", *args],
            returncode=1,
            stdout="",
            stderr=str(exc),
        )


def _systemd_quote(value: str | Path) -> str:
    text = str(value)
    if not text:
        return '""'
    if re.search(r"\s", text):
        return '"' + text.replace('"', r"\"") + '"'
    return text
