from descry.models import (
    Evidence,
    FeedbackEvent,
    Finding,
    FindingSource,
    Severity,
    WorkerReport,
    WorkerType,
)


def _finding(
    anchor: str = "GET /api/users",
    rule: str = "sast.sql-injection",
) -> Finding:
    return Finding(
        rule=rule,
        severity=Severity.HIGH,
        confidence=0.92,
        title="User-controlled SQL query",
        evidence=Evidence(
            file="app/api/users/route.ts",
            line_start=8,
            anchor=anchor,
            snippet_hash="abc123",
        ),
        source=FindingSource(
            worker=WorkerType.MOCK,
            playbook=rule,
            playbook_version=1,
        ),
    )


def test_finding_id_is_stable_for_rule_file_and_anchor() -> None:
    first = _finding()
    second = _finding()
    moved_line = _finding()
    moved_line.evidence.line_start = 42

    assert first.id == second.id
    assert first.id == moved_line.id
    assert first.id != _finding(anchor="POST /api/users").id


def test_worker_report_validates_nested_findings() -> None:
    finding = _finding()

    report = WorkerReport.model_validate(
        {
            "task_id": "task-1",
            "worker": "mock",
            "playbook": "sast.sql-injection",
            "playbook_version": 1,
            "findings": [finding.model_dump(mode="json")],
        }
    )

    assert report.worker == WorkerType.MOCK
    assert report.findings[0].id == finding.id
    assert report.partial is False


def test_feedback_event_creation_defaults() -> None:
    event = FeedbackEvent(
        finding_id="abc12345",
        action="fp",
        comment="Generated route is safe",
    )

    assert event.finding_id == "abc12345"
    assert event.action == "fp"
    assert event.user == "user"
    assert event.comment == "Generated route is safe"
    assert event.timestamp is not None
