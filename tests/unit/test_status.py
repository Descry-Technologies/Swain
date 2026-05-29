import json
import os
from pathlib import Path

import pytest

from descry.commands.history import load_latest_findings
from descry.commands.status import _rank_open_findings, run_status
from descry.memory.store import MemoryStore


@pytest.mark.asyncio
async def test_status_without_profile_does_not_create_descry_dir(
    tmp_path: Path,
) -> None:
    await run_status(tmp_path)

    assert not (tmp_path / ".swain").exists()


def test_status_ranks_open_findings_by_severity_then_confidence() -> None:
    findings = [
        _finding("medium-1", "medium", 0.99),
        _finding("high-1", "high", 0.70),
        _finding("critical-1", "critical", 0.50),
        _finding("closed-critical", "critical", 1.0, status="fixed"),
        _finding("high-2", "high", 0.95),
    ]

    ranked = _rank_open_findings(findings)

    assert [finding["id"] for finding in ranked] == [
        "critical-1",
        "high-2",
        "high-1",
        "medium-1",
    ]


def test_load_latest_findings_reads_newest_detail_history(
    tmp_path: Path,
) -> None:
    store = MemoryStore(tmp_path)
    old = store.history_dir / "old-findings.json"
    new = store.history_dir / "new-findings.json"
    old.write_text(json.dumps([_finding("old", "high", 0.9)]))
    new.write_text(json.dumps([_finding("new", "high", 0.9)]))

    os.utime(old, (1, 1))
    os.utime(new, (2, 2))

    findings = load_latest_findings(store)

    assert findings[0]["id"] == "new"


def test_load_latest_findings_uses_demo_history_fixture(
    tmp_path: Path,
) -> None:
    store = MemoryStore(tmp_path)
    demo_history = store.root / "demo-history"
    demo_history.mkdir()
    (demo_history / "demo-findings.json").write_text(
        json.dumps([_finding("demo", "critical", 0.9)])
    )

    findings = load_latest_findings(store)

    assert findings[0]["id"] == "demo"


def _finding(
    finding_id: str,
    severity: str,
    confidence: float,
    *,
    status: str = "open",
) -> dict:
    return {
        "id": finding_id,
        "rule": "sast.auth.python",
        "severity": severity,
        "confidence": confidence,
        "title": f"{severity} finding",
        "evidence": {
            "file": "backend/app/api/v1/auth.py",
            "line_start": 42,
            "anchor": finding_id,
        },
        "lifecycle": {"status": status},
    }
