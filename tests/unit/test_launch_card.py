from pathlib import Path

from descry.commands.launch_card import build_launch_card_data, write_launch_card_svg
from descry.memory.config import SwainConfig
from descry.memory.profile import ProjectProfile
from descry.memory.store import MemoryStore
from descry.models import (
    Evidence,
    Exploitability,
    Finding,
    FindingSource,
    Severity,
    WorkerType,
)
from descry.orchestrator.lead import _save_history


def test_launch_card_turns_history_into_shareable_blocked_verdict(
    tmp_path: Path,
) -> None:
    store = MemoryStore(tmp_path)
    ProjectProfile(
        repo_name="demo-saas",
        app_purpose="A billing app for solo builders",
        languages=["python"],
        frameworks=["fastapi", "react"],
        has_auth=True,
        has_payments=True,
    ).save(store)
    SwainConfig.completed(worker_mode="codex").save(store)
    finding = Finding(
        rule="sast.auth.python",
        severity=Severity.HIGH,
        confidence=0.93,
        title="Unauthenticated tenant admin endpoint",
        evidence=Evidence(
            file="backend/app/api/admin.py",
            line_start=12,
            anchor="GET /admin/tenant",
        ),
        exploitability=Exploitability(
            network_exposed=True,
            requires_auth=False,
        ),
        source=FindingSource(
            worker=WorkerType.CLAUDE,
            playbook="sast.auth.python",
            playbook_version=1,
        ),
    )
    _save_history(store, "run123", [finding])

    data = build_launch_card_data(tmp_path)
    svg_path = tmp_path / "card.svg"
    write_launch_card_svg(data, svg_path)
    svg = svg_path.read_text()

    assert data.verdict == "BLOCKED"
    assert data.launch_blockers == 1
    assert data.top_issue_id == finding.id[:8]
    assert "Unauthenticated" in svg
    assert "endpoint" in svg
    assert "swain.sh" in svg
    assert "AI security for vibe coders" in svg


def test_launch_card_without_scan_history_prompts_for_scan(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)
    ProjectProfile(repo_name="fresh-app", languages=["python"]).save(store)

    data = build_launch_card_data(tmp_path)

    assert data.verdict == "NO SCAN YET"
    assert data.next_command.endswith("swain scan .") or "swain scan" in (
        data.next_command
    )
