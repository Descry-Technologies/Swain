"""
Mock worker for tests and offline development.
Returns deterministic findings from fixture files or empty reports.
"""

from __future__ import annotations

import json
from pathlib import Path

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
        if self.fixture_path and self.fixture_path.exists():
            raw = json.loads(self.fixture_path.read_text())
        else:
            raw = {
                "schema_version": "1.0",
                "worker": "mock",
                "playbook": playbook_id or "mock",
                "playbook_version": playbook_version,
                "findings": [],
            }
        report = WorkerReport.model_validate({**raw, "task_id": task_id})
        return WorkerResult(report=report)
