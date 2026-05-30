"""
Mock worker for tests and offline development.
Returns deterministic findings from fixture files or empty reports.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from descry.models import WorkerReport, WorkerType
from descry.workers.base import BaseWorker, WorkerResult


class MockWorker(BaseWorker):
    worker_type = WorkerType.MOCK

    def __init__(self, fixture_path: Path | None = None) -> None:
        super().__init__(timeout_s=1)
        self.fixture_path = fixture_path

    def is_available(self) -> bool:
        return True

    async def _build_command(self, prompt: str, worktree: Path) -> list[str]:
        return ["echo", "{}"]

    async def run(
        self,
        task_id: str,
        prompt: str,
        files: list[Path],
        repo_root: Path,
        *,
        playbook_id: str = "",
        playbook_version: int = 1,
        timeout_s: int | None = None,
    ) -> WorkerResult:
        raw = self._load_report(repo_root, playbook_id)
        if raw is not None:
            report_data = raw
        else:
            report_data = {
                "schema_version": "1.0",
                "worker": "mock",
                "playbook": playbook_id or "mock",
                "playbook_version": playbook_version,
                "findings": [],
            }
        report = WorkerReport.model_validate({**report_data, "task_id": task_id})
        return WorkerResult(report=report)

    def _load_report(
        self,
        repo_root: Path,
        playbook_id: str,
    ) -> dict[str, Any] | None:
        if self.fixture_path and self.fixture_path.exists():
            raw = json.loads(self.fixture_path.read_text())
            return raw if isinstance(raw, dict) else {"findings": raw}

        demo_history = repo_root / ".swain" / "demo-history"
        if not demo_history.is_dir():
            return None
        history_files = sorted(demo_history.glob("*-findings.json"), reverse=True)
        if not history_files:
            return None
        raw = json.loads(history_files[0].read_text())
        findings = raw if isinstance(raw, list) else raw.get("findings", [])
        if not isinstance(findings, list):
            findings = []
        return {
            "schema_version": "1.0",
            "worker": "mock",
            "playbook": playbook_id or "mock",
            "playbook_version": 1,
            "findings": [
                finding
                for finding in findings
                if isinstance(finding, dict)
                and self._matches_playbook(finding, playbook_id)
            ],
        }

    def _matches_playbook(self, finding: dict[str, Any], playbook_id: str) -> bool:
        source = finding.get("source", {})
        source_playbook = source.get("playbook") if isinstance(source, dict) else ""
        return playbook_id in {
            str(source_playbook),
            str(finding.get("rule", "")),
        }
