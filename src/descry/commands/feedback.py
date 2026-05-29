"""descry feedback — record finding feedback and drive learning."""

from __future__ import annotations

from pathlib import Path

from rich.console import Console

from descry.memory.store import MemoryStore
from descry.memory.conventions import ConventionStore
from descry.memory.calibration import CalibrationStore
from descry.models import FeedbackEvent

console = Console()

VALID_ACTIONS = {"fp", "fix", "wontfix", "snooze"}


async def run_feedback(repo_root: Path, finding_id: str, action: str, comment: str = "") -> None:
    if action not in VALID_ACTIONS:
        console.print(f"[red]Invalid action '{action}'. Choose from: {', '.join(VALID_ACTIONS)}[/red]")
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
                console.print(f"  [dim]Pattern observed enough times — will suppress in future scans[/dim]")

    action_label = {"fp": "false positive", "fix": "fixed", "wontfix": "won't fix", "snooze": "snoozed"}
    console.print(f"[green]✓ Recorded '{action_label.get(action, action)}' for finding {finding_id[:8]}[/green]")
    if is_fp:
        console.print(f"  [dim]Pattern observed for promotion tracking (needs {3-1} more FP confirmations)[/dim]")


def _lookup_rule(store: MemoryStore, finding_id: str) -> str | None:
    import json
    for f in sorted(store.history_dir.glob("*.json"), reverse=True)[:5]:
        try:
            data = json.loads(f.read_text())
            for finding in data.get("findings", []):
                if finding.get("id", "").startswith(finding_id[:8]):
                    return finding.get("rule")
        except Exception:
            pass
    return None


def _lookup_file_glob(store: MemoryStore, finding_id: str) -> str | None:
    import json
    for f in sorted(store.history_dir.glob("*.json"), reverse=True)[:5]:
        try:
            data = json.loads(f.read_text())
            for finding in data.get("findings", []):
                if finding.get("id", "").startswith(finding_id[:8]):
                    ev = finding.get("evidence", {})
                    fp = ev.get("file", "")
                    # Convert to glob: src/components/Foo.tsx -> src/components/**
                    parts = fp.split("/")
                    if len(parts) > 1:
                        return "/".join(parts[:-1]) + "/**"
                    return "**"
        except Exception:
            pass
    return None


def _lookup_severity(store: MemoryStore, finding_id: str) -> str | None:
    import json
    for f in sorted(store.history_dir.glob("*.json"), reverse=True)[:5]:
        try:
            data = json.loads(f.read_text())
            for finding in data.get("findings", []):
                if finding.get("id", "").startswith(finding_id[:8]):
                    return finding.get("severity")
        except Exception:
            pass
    return None
