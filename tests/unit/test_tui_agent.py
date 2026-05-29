from pathlib import Path
from types import SimpleNamespace

from descry.models import Evidence, Finding, FindingSource, Severity, WorkerType
from descry.tui.app import Sidebar, SwainAgent
from descry.tui.voice import AgentVoice


def _agent() -> SwainAgent:
    app = SimpleNamespace(voice=AgentVoice(), repo_path=Path.cwd() / "repo")
    return SwainAgent(app)  # type: ignore[arg-type]


def _finding() -> Finding:
    return Finding(
        rule="sast.payments",
        severity=Severity.HIGH,
        confidence=0.9,
        title="Client controls subscription state",
        evidence=Evidence(file="backend/app/api/billing.py", anchor="POST /billing"),
        source=FindingSource(
            worker=WorkerType.CLAUDE,
            playbook="sast.payments",
            playbook_version=1,
        ),
    )


def test_local_priority_question_works_without_llm() -> None:
    agent = _agent()
    finding = _finding()
    agent._last_findings = [finding]

    answer = agent._try_local_answer("what should I fix first?")

    assert finding.id[:8] in answer
    assert "/fix" in answer


def test_local_launch_question_sets_market_ready_bar() -> None:
    answer = _agent()._try_local_answer("are we ready to ship?")

    assert "auth" in answer
    assert "payments" in answer
    assert "uploads" in answer


def test_sidebar_tracks_scan_subagent_progress() -> None:
    sidebar = Sidebar()

    sidebar.record_scan_event(
        "sast.payments: codex reviewing 8 files"
    )
    sidebar.record_scan_event(
        "sast.payments: codex returned 1 finding"
    )

    assert sidebar.scan_phase == "codex subagent active"
    assert "sast.payments: codex done" in sidebar.subagents


def test_scan_progress_hides_waiting_events_and_summarizes_tasks() -> None:
    agent = _agent()

    assert (
        agent._visible_scan_line("sast.payments: waiting for codex subagent")
        is None
    )
    line = agent._visible_scan_line("sast.payments: codex reviewing 8 files")

    assert line is not None
    assert "Payments" in line
    assert "reviewing 8 files" in line


def test_scan_detail_focus_parses_short_command() -> None:
    agent = _agent()

    assert agent._scan_detail_focus("/scan details auth") == "auth"
    assert agent._scan_detail_focus("/details payments") == "payments"
