from pathlib import Path
from types import SimpleNamespace

from descry.models import Evidence, Finding, FindingSource, Severity, WorkerType
from descry.tui.app import SwainAgent
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
