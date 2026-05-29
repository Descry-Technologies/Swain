"""swain scan — run a mission."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from descry.memory.calibration import CalibrationStore
from descry.memory.config import SwainConfig
from descry.memory.conventions import ConventionStore
from descry.memory.profile import ProjectProfile
from descry.memory.scheduler import ScheduleStore
from descry.memory.store import MemoryStore
from descry.models import Finding, Severity
from descry.orchestrator.executor import Executor
from descry.orchestrator.planner import Planner
from descry.playbooks.loader import PlaybookLoader
from descry.resources import builtin_playbooks_dir
from descry.scanners.inventory import RepoInventory
from descry.scanners.secrets import SecretsScanner
from descry.workers.configured_pool import build_worker_pool

console = Console()

SEVERITY_COLOR = {
    Severity.CRITICAL: "bold red",
    Severity.HIGH: "red",
    Severity.MEDIUM: "yellow",
    Severity.LOW: "cyan",
    Severity.INFO: "dim",
}


def _terminal_event(text: str) -> None:
    console.print(f"[dim]  - {text}[/dim]")


async def run_scan(
    repo_root: Path,
    trigger: str = "manual",
    output: str = "terminal",
    out_file: str | None = None,
    mock: bool = False,
) -> None:
    profile_path = repo_root / ".swain" / "profile.yaml"
    if not profile_path.exists():
        console.print(
            "[yellow]No .swain/profile.yaml found. "
            "Run [bold]swain setup[/bold] first.[/yellow]"
        )
        return

    store = MemoryStore(repo_root)

    # Load memory
    profile = ProjectProfile.load(store)
    conventions = ConventionStore(store)
    calibration = CalibrationStore(store)
    schedule = ScheduleStore(store)

    # Run deterministic scanners first
    console.print("[dim]Running deterministic scanners...[/dim]")
    inventory = RepoInventory.scan(repo_root, prev_deps=profile.deps)
    secret_hits = await SecretsScanner().run(repo_root)

    if secret_hits:
        console.print(
            f"[bold red]🚨 {len(secret_hits)} potential secret(s) "
            "detected by static scan![/bold red]"
        )

    # Build worker pool from first-run setup.
    config = SwainConfig.load(store)
    if output == "terminal":
        if mock:
            console.print("[dim]Worker mode: mock offline demo[/dim]")
        else:
            console.print(f"[dim]Worker mode: {config.worker_summary()}[/dim]")
    pool = build_worker_pool(config, mock=mock)

    # Load playbooks
    user_pb_dir = store.root / "playbooks"
    loader = PlaybookLoader(builtin_dir=builtin_playbooks_dir(), user_dir=user_pb_dir)

    # Plan mission
    planner = Planner(loader, schedule)
    mission = planner.plan(trigger, inventory)

    console.print(
        f"[dim]Mission {mission.id}: {len(mission.tasks)} "
        "playbook(s) to run[/dim]"
    )

    findings: list[Finding] = []

    def on_finding(f: Finding) -> None:
        findings.append(f)
        if output == "terminal":
            color = SEVERITY_COLOR.get(f.severity, "white")
            console.print(
                f"  [{color}]{f.severity.upper()}[/{color}] {f.title} "
                f"({f.evidence.file}:{f.evidence.line_start or '?'})"
            )

    # Execute
    executor = Executor(pool, loader, profile, conventions, calibration, repo_root)
    progress_event = _terminal_event if output == "terminal" else None
    findings = await executor.execute(
        mission,
        on_finding=on_finding if output == "terminal" else None,
        on_event=progress_event,
    )
    task_warnings = executor.task_warnings

    # Increment run count; check if schedule recompute needed
    schedule.increment_run_count()
    if schedule.needs_recompute():
        console.print("[dim]Recomputing schedule based on run history...[/dim]")
        # Simple heuristic recompute — full synthesizer in Phase 2
        schedule.apply_recompute(schedule._data.get("schedules", []))

    # Save run to history
    _save_history(store, mission.id, findings)

    # Output
    if output == "terminal":
        _render_terminal(findings, secret_hits, task_warnings)
    elif output == "json":
        result = _to_json(findings, secret_hits, mission.id, task_warnings)
        if out_file:
            Path(out_file).write_text(json.dumps(result, indent=2, default=str))
        else:
            console.print_json(json.dumps(result, default=str))
    elif output == "markdown":
        md = _to_markdown(findings, secret_hits, mission.id, task_warnings)
        if out_file:
            Path(out_file).write_text(md)
        else:
            console.print(md)


def _render_terminal(
    findings: list[Finding],
    secret_hits: list,
    task_warnings: list[str] | None = None,
) -> None:
    task_warnings = task_warnings or []
    console.print()
    if not findings and not secret_hits:
        if task_warnings:
            console.print(
                Panel.fit(
                    "[yellow]No findings returned, but scan warnings "
                    "occurred.[/yellow]",
                    title="Swain Scan Incomplete",
                )
            )
            for warning in task_warnings:
                console.print(f"  ⚠ {warning}")
            return
        console.print(
            Panel.fit("[green]✓ No findings[/green]", title="Swain Scan Complete")
        )
        return

    table = Table(title=f"Swain Findings ({len(findings)} total)", show_lines=True)
    table.add_column("Severity", style="bold", width=10)
    table.add_column("Rule", width=30)
    table.add_column("Title", width=40)
    table.add_column("File", width=30)
    table.add_column("Conf.", width=6)

    for f in sorted(findings, key=lambda x: list(Severity).index(x.severity)):
        color = SEVERITY_COLOR.get(f.severity, "white")
        table.add_row(
            f"[{color}]{f.severity.upper()}[/{color}]",
            f.rule,
            f.title,
            f"{f.evidence.file}:{f.evidence.line_start or '?'}",
            f"{f.confidence:.0%}",
        )

    console.print(table)

    if secret_hits:
        console.print(
            f"\n[bold red]Static secret scan: {len(secret_hits)} hit(s)[/bold red]"
        )
        for h in secret_hits:
            console.print(f"  🔑 {h.rule} in {h.file}:{h.line}")

    if task_warnings:
        console.print("\n[yellow]Scan warnings[/yellow]")
        for warning in task_warnings:
            console.print(f"  ⚠ {warning}")


def _to_json(
    findings: list[Finding],
    secret_hits: list,
    run_id: str,
    task_warnings: list[str] | None = None,
) -> dict:
    task_warnings = task_warnings or []
    return {
        "run_id": run_id,
        "timestamp": datetime.now(UTC).isoformat(),
        "complete": not task_warnings,
        "warnings": task_warnings,
        "finding_count": len(findings),
        "findings": [f.model_dump() for f in findings],
        "secret_scan_hits": len(secret_hits),
    }


def _to_markdown(
    findings: list[Finding],
    secret_hits: list,
    run_id: str,
    task_warnings: list[str] | None = None,
) -> str:
    task_warnings = task_warnings or []
    lines = [
        "# Swain Security Report\n",
        f"**Run ID**: `{run_id}`  ",
        f"**Date**: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M')} UTC\n",
    ]
    if task_warnings:
        lines.append("\n## Scan Warnings\n")
        for warning in task_warnings:
            lines.append(f"- {warning}")
    if not findings and not secret_hits:
        if task_warnings:
            lines.append(
                "\nNo findings were returned by completed playbooks, "
                "but this scan was incomplete.\n"
            )
        else:
            lines.append("\n✅ No findings.\n")
        return "\n".join(lines)
    for sev in Severity:
        group = [f for f in findings if f.severity == sev]
        if not group:
            continue
        lines.append(f"\n## {sev.upper()} ({len(group)})\n")
        for f in group:
            lines.append(f"### {f.title}")
            lines.append(f"- **Rule**: `{f.rule}`")
            lines.append(
                f"- **File**: `{f.evidence.file}:{f.evidence.line_start or '?'}`"
            )
            lines.append(f"- **Confidence**: {f.confidence:.0%}")
            if f.description:
                lines.append(f"\n{f.description}\n")
            if f.remediation.summary:
                lines.append(f"\n**Fix**: {f.remediation.summary}\n")
    return "\n".join(lines)


def _save_history(store: MemoryStore, run_id: str, findings: list[Finding]) -> None:
    import json as _json
    timestamp = datetime.now(UTC)
    record = {
        "run_id": run_id,
        "timestamp": timestamp.isoformat(),
        "finding_count": len(findings),
        "severities": {
            s.value: sum(1 for f in findings if f.severity == s)
            for s in Severity
        },
    }
    path = store.history_dir / f"{timestamp.strftime('%Y%m%d-%H%M%S')}-{run_id}.json"
    path.write_text(_json.dumps(record, indent=2))

    findings_path = store.history_dir / f"{run_id}-findings.json"
    payload = [finding.model_dump(mode="json") for finding in findings]
    findings_path.write_text(_json.dumps(payload, indent=2))
