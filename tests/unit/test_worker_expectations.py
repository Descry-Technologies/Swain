import json
from pathlib import Path

import pytest

from descry.memory.calibration import CalibrationStore
from descry.memory.conventions import ConventionStore
from descry.memory.profile import ProjectProfile
from descry.memory.store import MemoryStore
from descry.models import WorkerType
from descry.orchestrator.executor import Executor
from descry.orchestrator.planner import Planner
from descry.orchestrator.pool import WorkerPool
from descry.playbooks.loader import PlaybookLoader
from descry.resources import builtin_playbooks_dir
from descry.scanners.inventory import RepoInventory
from descry.workers.base import BaseWorker, WorkerResult

ROOT = Path(__file__).parents[2]
LAUNCH_RISK_REPO = ROOT / "tests" / "fixtures" / "repos" / "launch-risk-saas"
REPORTS_DIR = ROOT / "tests" / "fixtures" / "worker_reports" / "launch-risk-saas"


class NoSchedule:
    def get_schedules_for_trigger(self, trigger: str) -> list[dict]:
        return []

    def upsert_risk_trigger(
        self,
        playbook: str,
        paths: list[str],
        reason: str,
    ) -> None:
        return None


class FixtureClaudeWorker(BaseWorker):
    worker_type = WorkerType.CLAUDE

    def __init__(self, reports_dir: Path) -> None:
        super().__init__()
        self.reports_dir = reports_dir

    def is_available(self) -> bool:
        return True

    async def _build_command(self, prompt: str, worktree: Path) -> list[str]:
        return ["fixture-worker"]

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
        output = (self.reports_dir / f"{playbook_id}.json").read_text()
        return self._parse_output(
            task_id,
            output,
            "",
            0,
            playbook_id,
            playbook_version,
        )


@pytest.mark.asyncio
async def test_launch_risk_expected_worker_reports_flow_through_executor(
    tmp_path: Path,
) -> None:
    inventory = RepoInventory.scan(LAUNCH_RISK_REPO)
    loader = PlaybookLoader(builtin_playbooks_dir())
    mission = Planner(loader, NoSchedule()).plan("manual", inventory)

    pool = WorkerPool(max_concurrent=4, max_per_type=4)
    pool.register(FixtureClaudeWorker(REPORTS_DIR))

    store = MemoryStore(tmp_path)
    profile = ProjectProfile(
        languages=inventory.languages,
        frameworks=inventory.frameworks,
        deps=inventory.deps,
        deploy_target=inventory.deploy_target,
        db=inventory.db,
        has_auth=inventory.has_auth,
        has_payments=inventory.has_payments,
        has_file_upload=inventory.has_file_upload,
        has_llm_features=inventory.has_llm_features,
        repo_name="launch-risk-saas",
    )

    executor = Executor(
        pool,
        loader,
        profile,
        ConventionStore(store),
        CalibrationStore(store),
        LAUNCH_RISK_REPO,
    )
    findings = await executor.execute(mission)

    expected = _expected_findings()
    observed = {
        (finding.rule, finding.evidence.file, finding.title)
        for finding in findings
    }

    assert executor.task_warnings == []
    assert observed == expected
    assert all(finding.id for finding in findings)
    assert all(finding.source.run_id for finding in findings)
    assert all(finding.source.worker == WorkerType.CLAUDE for finding in findings)


def _expected_findings() -> set[tuple[str, str, str]]:
    expected = set()
    for report_path in REPORTS_DIR.glob("*.json"):
        raw = json.loads(report_path.read_text())
        for finding in raw.get("findings", []):
            expected.add((
                finding["rule"],
                finding["evidence"]["file"],
                finding["title"],
            ))
    return expected
