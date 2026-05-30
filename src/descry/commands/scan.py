"""swain scan — run a mission."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from descry.memory.coworker import DecisionRecord, FixQueueItem
from descry.memory.store import MemoryStore
from descry.models import Finding, Severity
from descry.orchestrator.lead import LeadOrchestrationError, LeadOrchestrator
from descry.scanners.secrets import SecretHit

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
    fresh: bool = False,
) -> None:
    profile_path = repo_root / ".swain" / "profile.yaml"
    if not profile_path.exists():
        console.print(
            "[yellow]No .swain/profile.yaml found. "
            "Run [bold]swain setup[/bold] first.[/yellow]"
        )
        return

    lead = LeadOrchestrator(repo_root)
    try:
        result = await lead.run_recon(
            trigger=trigger,
            objective="manual scan",
            mock=mock,
            persist=not mock,
            use_cache=not fresh,
            on_event=_terminal_event if output == "terminal" else None,
        )
    except LeadOrchestrationError as exc:
        console.print(f"[yellow]{exc}[/yellow]")
        return

    # Output
    if output == "terminal":
        _render_terminal(result.findings, result.secret_hits, result.warnings)
        _render_decisions(result.decisions)
        _render_fix_queue(result.fix_queue)
    elif output == "json":
        payload = _to_json(
            result.findings,
            result.secret_hits,
            result.mission_id,
            result.warnings,
            decisions=result.decisions,
            fix_queue=result.fix_queue,
        )
        if out_file:
            Path(out_file).write_text(json.dumps(payload, indent=2, default=str))
        else:
            console.print_json(json.dumps(payload, default=str))
    elif output == "markdown":
        md = _to_markdown(
            result.findings,
            result.secret_hits,
            result.mission_id,
            result.warnings,
            decisions=result.decisions,
            fix_queue=result.fix_queue,
        )
        if out_file:
            Path(out_file).write_text(md)
        else:
            console.print(md)


def _render_terminal(
    findings: list[Finding],
    secret_hits: list[SecretHit],
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
            Panel(
                "[bold green]✓  Clean scan — no findings, no blockers.[/bold green]\n\n"
                "  You're cleared to ship.\n\n"
                "  [dim]Run [bold]swain share[/bold] to generate a launch card "
                "for social.[/dim]",
                title="[bold green]Swain[/bold green]",
                border_style="green",
                padding=(1, 2),
            )
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


def _render_decisions(decisions: list[DecisionRecord]) -> None:
    if not decisions:
        return
    console.print("\n[bold]Decision log[/bold]")
    for decision in decisions[-6:]:
        style = {
            "blocker": "bold red",
            "warning": "yellow",
            "info": "dim",
        }.get(decision.level.value, "dim")
        console.print(f"  [{style}]• {decision.summary}[/{style}]")
        if decision.rationale:
            console.print(f"    [dim]{decision.rationale}[/dim]")
        if decision.next_step:
            console.print(f"    [cyan]{decision.next_step}[/cyan]")


def _render_fix_queue(fix_queue: list[FixQueueItem]) -> None:
    if not fix_queue:
        return
    console.print("\n[bold]Fix queue[/bold]")
    for item in fix_queue[:5]:
        console.print(
            "  • "
            f"[{SEVERITY_COLOR.get(Severity(item.severity), 'white')}]"
            f"{item.severity.upper()}[/] "
            f"`{item.finding_id[:8]}` {item.title} "
            f"([dim]{item.file}:{item.line or '?'}[/dim])"
        )
    first = fix_queue[0]
    console.print(f"  Next: [cyan]swain fix {first.finding_id[:8]}[/cyan]")


def _to_json(
    findings: list[Finding],
    secret_hits: list[SecretHit],
    run_id: str,
    task_warnings: list[str] | None = None,
    decisions: list[DecisionRecord] | None = None,
    fix_queue: list[FixQueueItem] | None = None,
) -> dict[str, Any]:
    task_warnings = task_warnings or []
    decisions = decisions or []
    fix_queue = fix_queue or []
    return {
        "run_id": run_id,
        "timestamp": datetime.now(UTC).isoformat(),
        "complete": not task_warnings,
        "warnings": task_warnings,
        "finding_count": len(findings),
        "findings": [f.model_dump() for f in findings],
        "secret_scan_hits": len(secret_hits),
        "decisions": [decision.model_dump(mode="json") for decision in decisions],
        "fix_queue": [item.model_dump(mode="json") for item in fix_queue],
    }


def _to_markdown(
    findings: list[Finding],
    secret_hits: list[SecretHit],
    run_id: str,
    task_warnings: list[str] | None = None,
    decisions: list[DecisionRecord] | None = None,
    fix_queue: list[FixQueueItem] | None = None,
) -> str:
    task_warnings = task_warnings or []
    decisions = decisions or []
    fix_queue = fix_queue or []
    lines = [
        "# Swain Security Report\n",
        f"**Run ID**: `{run_id}`  ",
        f"**Date**: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M')} UTC\n",
    ]
    if decisions:
        lines.append("\n## Decision Log\n")
        for decision in decisions:
            lines.append(f"- **{decision.level.value}**: {decision.summary}")
            if decision.rationale:
                lines.append(f"  {decision.rationale}")
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
    if fix_queue:
        lines.append("\n## Fix Queue\n")
        for item in fix_queue:
            lines.append(
                f"- `{item.finding_id[:8]}` {item.severity.upper()} "
                f"{item.title} — {item.rationale}"
            )
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
