import json

from descry.commands.feedback import _lookup_file_glob, _lookup_rule, _lookup_severity
from descry.commands.scan import _save_history
from descry.memory.store import MemoryStore
from descry.models import Evidence, Finding, FindingSource, Severity, WorkerType


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
