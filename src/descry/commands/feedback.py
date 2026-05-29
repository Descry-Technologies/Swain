"""swain feedback — record finding feedback and drive learning."""

from __future__ import annotations

from pathlib import Path

from rich.console import Console

from descry.commands.history import lookup_finding
from descry.memory.calibration import CalibrationStore
from descry.memory.conventions import ConventionStore
from descry.memory.store import MemoryStore
from descry.models import FeedbackEvent

console = Console()

VALID_ACTIONS = {"fp", "fix", "wontfix", "snooze"}


async def run_feedback(
    repo_root: Path,
    finding_id: str,
    action: str,
    comment: str = "",
) -> None:
    if action not in VALID_ACTIONS:
        console.print(
            f"[red]Invalid action '{action}'. Choose from: "
            f"{', '.join(VALID_ACTIONS)}[/red]"
        )
        return

    store = MemoryStore(repo_root)
    conventions = ConventionStore(store)
    calibration = CalibrationStore(store)

    event = FeedbackEvent(finding_id=finding_id, action=action, comment=comment)

    # Persist feedback
    store.append_jsonl(store.feedback_path, event.model_dump(mode="json"))

    # Update calibration
    is_tp = action == "fix"
    is_fp = action == "fp"

    # To update calibration we need the rule — look it up from history
    rule = _lookup_rule(store, finding_id)
    if rule:
        if is_tp:
            calibration.record(rule, is_tp=True)
        elif is_fp:
            calibration.record(rule, is_tp=False)
            # Try promoting to convention
            file_glob = _lookup_file_glob(store, finding_id) or "**"
            severity = _lookup_severity(store, finding_id) or "medium"
            conventions.record_fp(finding_id, rule, file_glob, severity)
            # Check if convention was just promoted
            active = conventions.get_active_conventions(rule=rule)
            if active:
                console.print(f"[green]✓ Convention promoted for rule '{rule}'[/green]")
                console.print(
                    "  [dim]Pattern observed enough times — will suppress "
                    "in future scans[/dim]"
                )

    action_label = {
        "fp": "false positive",
        "fix": "fixed",
        "wontfix": "won't fix",
        "snooze": "snoozed",
    }
    console.print(
        f"[green]✓ Recorded '{action_label.get(action, action)}' "
        f"for finding {finding_id[:8]}[/green]"
    )
    if is_fp:
        console.print(
            "  [dim]Pattern observed for promotion tracking "
            f"(needs {3 - 1} more FP confirmations)[/dim]"
        )


def _lookup_rule(store: MemoryStore, finding_id: str) -> str | None:
    finding = lookup_finding(store, finding_id)
    return finding.get("rule") if finding else None


def _lookup_file_glob(store: MemoryStore, finding_id: str) -> str | None:
    finding = lookup_finding(store, finding_id)
    if not finding:
        return None

    ev = finding.get("evidence", {})
    fp = ev.get("file", "")
    # Convert to glob: src/components/Foo.tsx -> src/components/**
    parts = fp.split("/")
    if len(parts) > 1:
        return "/".join(parts[:-1]) + "/**"
    return "**"


def _lookup_severity(store: MemoryStore, finding_id: str) -> str | None:
    finding = lookup_finding(store, finding_id)
    return finding.get("severity") if finding else None
