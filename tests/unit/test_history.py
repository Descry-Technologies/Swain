import json

from descry.commands.feedback import _lookup_file_glob, _lookup_rule, _lookup_severity
from descry.memory.store import MemoryStore
from descry.models import Evidence, Finding, FindingSource, Severity, WorkerType
from descry.orchestrator.lead import _save_history


def test_scan_history_writes_findings_detail_for_feedback_lookup(tmp_path) -> None:
    store = MemoryStore(tmp_path)
    finding = Finding(
        rule="sast.sql-injection",
        severity=Severity.HIGH,
        confidence=0.95,
        title="Raw SQL query uses request parameter",
        evidence=Evidence(
            file="app/api/users/route.ts",
            line_start=7,
            anchor="GET /api/users",
        ),
        source=FindingSource(
            worker=WorkerType.MOCK,
            playbook="sast.sql-injection",
            playbook_version=1,
        ),
    )

    _save_history(store, "run123", [finding])

    detail_path = store.history_dir / "run123-findings.json"
    detail = json.loads(detail_path.read_text())

    assert detail[0]["id"] == finding.id
    assert _lookup_rule(store, finding.id[:8]) == "sast.sql-injection"
    assert _lookup_file_glob(store, finding.id[:8]) == "app/api/users/**"
    assert _lookup_severity(store, finding.id[:8]) == "high"


def test_mock_scan_history_is_skipped_for_feedback_lookup(tmp_path) -> None:
    store = MemoryStore(tmp_path)
    real = _finding("real", "Real finding", WorkerType.CLAUDE)
    mock = _finding("mock", "Mock finding", WorkerType.MOCK)

    _save_history(store, "realrun", [real])
    _save_history(store, "mockrun", [mock], mock=True)

    assert _lookup_rule(store, mock.id[:8]) is None
    assert _lookup_rule(store, real.id[:8]) == "sast.sql-injection"


def _finding(anchor: str, title: str, worker: WorkerType) -> Finding:
    return Finding(
        rule="sast.sql-injection",
        severity=Severity.HIGH,
        confidence=0.95,
        title=title,
        evidence=Evidence(
            file="app/api/users/route.ts",
            line_start=7,
            anchor=anchor,
        ),
        source=FindingSource(
            worker=worker,
            playbook="sast.sql-injection",
            playbook_version=1,
        ),
    )
