"""swain status — show posture, conventions, and schedule."""

from __future__ import annotations

from pathlib import Path

from rich.console import Console
from rich.panel import Panel

from descry.commands.history import load_latest_findings, summary_history_paths
from descry.memory.conventions import ConventionStore
from descry.memory.profile import ProjectProfile
from descry.memory.scheduler import ScheduleStore
from descry.memory.store import MemoryStore
from descry.orchestrator.lead import LeadOrchestrator

console = Console()

_SEVERITY_RANK = {
    "critical": 0,
    "high": 1,
    "medium": 2,
    "low": 3,
    "info": 4,
}


async def run_status(repo_root: Path) -> None:
    profile_path = repo_root / ".swain" / "profile.yaml"
    if not profile_path.exists():
        console.print(
            "[yellow]No .swain/profile.yaml found. "
            "Run [bold]swain init[/bold] or [bold]swain scan[/bold] first.[/yellow]"
        )
        return

    store = MemoryStore(repo_root)

    profile = ProjectProfile.load(store)
    conventions = ConventionStore(store)
    schedule = ScheduleStore(store)
    lead_status = LeadOrchestrator(repo_root).status_snapshot()

    try:
        display_path = "~/" + str(repo_root.relative_to(Path.home()))
    except ValueError:
        display_path = str(repo_root)
    console.print(
        Panel.fit(
            f"[bold cyan]Swain Status[/bold cyan]\n[dim]{display_path}[/dim]",
        )
    )

    # Profile
    console.print(f"\n[bold]Project[/bold]: {profile.app_purpose or profile.repo_name}")
    console.print(
        f"[bold]Stack[/bold]: {', '.join(profile.frameworks or profile.languages)}"
    )
    if profile.user_priorities:
        console.print(
            f"[bold]Priorities[/bold]: {', '.join(profile.user_priorities[:3])}"
        )

    # Conventions
    active = conventions.get_active_conventions()
    console.print(f"\n[bold]Learned conventions[/bold]: {len(active)}")
    for c in active[:5]:
        console.print(f"  • {c['rule']} in {c['file_glob']}")

    # Schedule
    schedules = schedule._data.get("schedules", [])
    console.print(f"\n[bold]Active schedule[/bold]: {len(schedules)} playbook(s)")
    for s in schedules[:6]:
        trigger = s.get("trigger", "")
        trigger_label = f" [dim]({trigger})[/dim]" if trigger else ""
        console.print(f"  •  {s['playbook']}{trigger_label}")

    # Coworker mission state
    ledger = lead_status.ledger
    console.print("\n[bold]Mission[/bold]:")
    if ledger.phase.value == "idle":
        console.print("  • idle")
    else:
        console.print(
            f"  • {ledger.phase.value} — "
            f"{ledger.latest_summary or ledger.active_objective}"
        )
        if ledger.mission_id:
            console.print(f"  • mission `{ledger.mission_id}`")

    if lead_status.fix_queue:
        next_fix_item = lead_status.fix_queue[0]
        console.print(f"\n[bold]Fix queue[/bold]: {len(lead_status.fix_queue)}")
        console.print(
            f"  • next `{next_fix_item.finding_id[:8]}` — "
            f"{next_fix_item.title} ({next_fix_item.rationale})"
        )
    else:
        console.print("\n[bold]Fix queue[/bold]: empty")

    watch = lead_status.watch_state
    console.print("\n[bold]Watch[/bold]:")
    if watch.enabled:
        console.print(
            f"  • enabled every {watch.interval_s}s"
            f"{f' via {watch.service_name}' if watch.service_name else ''}"
        )
        console.print(
            f"  • last trigger: {watch.last_triggered_at or 'never'} "
            f"{watch.last_trigger_reason}"
        )
    else:
        console.print("  • not enabled")

    if lead_status.decisions:
        console.print("\n[bold]Latest decisions[/bold]:")
        for decision in lead_status.decisions[:5]:
            console.print(
                f"  • [{decision.level.value}] {decision.summary}"
                f"{f' — {decision.next_step}' if decision.next_step else ''}"
            )

    # Run history
    history_files = summary_history_paths(store)[:5]
    if history_files:
        import json
        console.print("\n[bold]Recent runs[/bold]:")
        for f in history_files:
            data = None
            try:
                data = json.loads(f.read_text())
            except Exception:
                data = None
            if not isinstance(data, dict):
                continue
            ts = data.get("timestamp", "")[:16]
            count = data.get("finding_count", 0)
            console.print(f"  • {ts}  {count} finding(s)")

    latest_findings = load_latest_findings(store)
    open_findings = _rank_open_findings(latest_findings)
    if open_findings:
        first = open_findings[0]
        first_id = _finding_id(first)
        console.print(f"\n[bold]Open findings[/bold]: {len(open_findings)}")
        for finding in open_findings[:5]:
            console.print(
                "  • "
                f"[{_severity_style(finding)}]{_severity(finding).upper()}[/] "
                f"`{_finding_id(finding)}` "
                f"{_title(finding)} "
                f"([dim]{_location(finding)}[/dim])"
            )
        console.print(
            "\n[bold]Fix first[/bold]: "
            f"`{first_id}` — {_title(first)}"
        )
        console.print(
            f"  Next: [cyan]swain fix {first_id} --path {repo_root}[/cyan]"
        )
        console.print(
            "  Wrong? "
            f"[cyan]swain feedback {first_id} fp --path {repo_root}[/cyan]"
        )
    elif latest_findings:
        console.print("\n[bold]Open findings[/bold]: 0 in the latest scan")
    else:
        console.print("\n[bold]Open findings[/bold]: no finding history yet")


def _rank_open_findings(findings: list[dict]) -> list[dict]:
    open_findings = [
        finding for finding in findings
        if finding.get("lifecycle", {}).get("status", "open") == "open"
    ]
    return sorted(open_findings, key=_finding_sort_key)


def _finding_sort_key(finding: dict) -> tuple[int, float, str]:
    return (
        _SEVERITY_RANK.get(_severity(finding), 99),
        -_confidence(finding),
        _title(finding).lower(),
    )


def _severity(finding: dict) -> str:
    return str(finding.get("severity") or "info").lower()


def _confidence(finding: dict) -> float:
    try:
        return float(finding.get("confidence") or 0)
    except (TypeError, ValueError):
        return 0.0


def _severity_style(finding: dict) -> str:
    return {
        "critical": "bold red",
        "high": "red",
        "medium": "yellow",
        "low": "cyan",
        "info": "dim",
    }.get(_severity(finding), "white")


def _finding_id(finding: dict) -> str:
    finding_id = str(finding.get("id") or "").strip()
    return finding_id[:8] if finding_id else "unknown"


def _title(finding: dict) -> str:
    return str(finding.get("title") or finding.get("rule") or "Untitled finding")


def _location(finding: dict) -> str:
    evidence = finding.get("evidence", {})
    if not isinstance(evidence, dict):
        return "unknown"
    file = str(evidence.get("file") or "unknown")
    line = evidence.get("line_start")
    return f"{file}:{line}" if line else file
