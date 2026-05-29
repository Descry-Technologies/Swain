"""descry status — show posture, conventions, and schedule."""

from __future__ import annotations

from pathlib import Path

from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from descry.memory.store import MemoryStore
from descry.memory.profile import ProjectProfile
from descry.memory.conventions import ConventionStore
from descry.memory.calibration import CalibrationStore
from descry.memory.scheduler import ScheduleStore

console = Console()


async def run_status(repo_root: Path) -> None:
    store = MemoryStore(repo_root)

    profile = ProjectProfile.load(store)
    conventions = ConventionStore(store)
    calibration = CalibrationStore(store)
    schedule = ScheduleStore(store)

    console.print(Panel.fit("[bold cyan]Descry Status[/bold cyan]", subtitle=str(repo_root)))

    # Profile
    console.print(f"\n[bold]Project[/bold]: {profile.app_purpose or profile.repo_name}")
    console.print(f"[bold]Stack[/bold]: {', '.join(profile.frameworks or profile.languages)}")
    if profile.user_priorities:
        console.print(f"[bold]Priorities[/bold]: {', '.join(profile.user_priorities[:3])}")

    # Conventions
    active = conventions.get_active_conventions()
    console.print(f"\n[bold]Learned conventions[/bold]: {len(active)}")
    for c in active[:5]:
        console.print(f"  • {c['rule']} in {c['file_glob']}")

    # Schedule
    schedules = schedule._data.get("schedules", [])
    console.print(f"\n[bold]Active schedule[/bold]: {len(schedules)} playbook(s)")
    for s in schedules[:6]:
        console.print(f"  • [{s['trigger']}] {s['playbook']}")

    # Run history
    history_files = sorted(store.history_dir.glob("*.json"), reverse=True)[:5]
    if history_files:
        import json
        console.print(f"\n[bold]Recent runs[/bold]:")
        for f in history_files:
            try:
                data = json.loads(f.read_text())
                ts = data.get("timestamp", "")[:16]
                count = data.get("finding_count", 0)
                console.print(f"  • {ts}  {count} finding(s)")
            except Exception:
                pass
