from pathlib import Path

import pytest

from descry.memory.config import SwainConfig
from descry.memory.coworker import CoworkerMemory
from descry.memory.profile import ProjectProfile
from descry.memory.store import MemoryStore
from descry.models import (
    Evidence,
    Exploitability,
    Finding,
    FindingSource,
    Severity,
    WorkerReport,
    WorkerType,
)
from descry.orchestrator.lead import LeadOrchestrator, _save_history
from descry.orchestrator.pool import WorkerPool
from descry.workers.base import BaseWorker, WorkerResult


class TimeoutWorker(BaseWorker):
    worker_type = WorkerType.CLAUDE

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
        return WorkerResult(report=None, timed_out=True, exit_code=-1)


class CountingWorker(BaseWorker):
    worker_type = WorkerType.CLAUDE

    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

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
        self.calls += 1
        return WorkerResult(
            report=WorkerReport(
                task_id=task_id,
                worker=WorkerType.CLAUDE,
                playbook=playbook_id,
                playbook_version=playbook_version,
                findings=[],
            )
        )


def test_natural_language_maps_to_coworker_actions(tmp_path: Path) -> None:
    lead = LeadOrchestrator(tmp_path)

    assert lead.interpret("watch this repo").action == "watch"
    scan = lead.interpret("scan this and tell me what blocks launch")
    assert scan.action == "scan"
    assert scan.launch_focus is True
    assert lead.interpret("what are you working on?").action == "status"
    assert lead.interpret("draft the first fix").action == "draft_fix"
    assert lead.interpret("ignore this pattern, it's expected").action == (
        "record_preference"
    )
    assert lead.interpret("show me the worker details").action == "details"


def test_fix_queue_orders_by_severity_confidence_exposure_and_launch_risk(
    tmp_path: Path,
) -> None:
    lead = LeadOrchestrator(tmp_path)
    exposed_auth = _finding(
        "sast.auth.python",
        Severity.HIGH,
        0.90,
        "Missing auth on tenant endpoint",
        network_exposed=True,
        requires_auth=False,
    )
    local_medium = _finding(
        "sast.misc",
        Severity.MEDIUM,
        0.99,
        "Local config issue",
    )

    queue = lead.build_fix_queue([local_medium, exposed_auth])

    assert queue[0].finding_id == exposed_auth.id
    assert queue[0].launch_risk is True
    assert "network-exposed without auth" in queue[0].rationale


@pytest.mark.asyncio
async def test_recon_persists_mission_decisions_and_fix_queue(
    tmp_path: Path,
) -> None:
    _init_repo_memory(tmp_path)

    result = await LeadOrchestrator(tmp_path).run_recon(mock=True)

    memory = CoworkerMemory(MemoryStore(tmp_path))
    ledger = memory.load_ledger()
    decisions = memory.recent_decisions()

    assert result.mission_id == ledger.mission_id
    assert ledger.phase.value in {"done", "fix_queue", "review"}
    assert ledger.latest_decision_ids
    assert decisions
    assert memory.load_fix_queue() == result.fix_queue


@pytest.mark.asyncio
async def test_recon_can_run_without_persisting_mock_state(
    tmp_path: Path,
) -> None:
    _init_repo_memory(tmp_path)

    result = await LeadOrchestrator(tmp_path).run_recon(mock=True, persist=False)

    store = MemoryStore(tmp_path)
    assert result.decisions
    assert result.mission_id
    assert not store.mission_ledger_path.exists()
    assert not store.decision_log_path.exists()
    assert not store.fix_queue_path.exists()
    assert not store.schedule_path.exists()
    assert not list(store.history_dir.glob("*.json"))


@pytest.mark.asyncio
async def test_worker_failures_create_warning_decisions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _init_repo_memory(tmp_path)

    def fake_pool(config: SwainConfig, *, mock: bool = False) -> WorkerPool:
        pool = WorkerPool(max_concurrent=1, max_per_type=1)
        pool.register(TimeoutWorker())
        return pool

    monkeypatch.setattr("descry.orchestrator.lead.build_worker_pool", fake_pool)

    result = await LeadOrchestrator(tmp_path).run_recon()

    warning_decisions = [
        decision for decision in result.decisions
        if decision.level.value == "warning"
    ]
    assert result.warnings
    assert warning_decisions
    assert any(decision.trusted is False for decision in warning_decisions)


@pytest.mark.asyncio
async def test_recon_reuses_cached_worker_results_for_same_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _init_repo_memory(tmp_path)
    worker = CountingWorker()

    def fake_pool(config: SwainConfig, *, mock: bool = False) -> WorkerPool:
        pool = WorkerPool(max_concurrent=1, max_per_type=1)
        pool.register(worker)
        return pool

    monkeypatch.setattr("descry.orchestrator.lead.build_worker_pool", fake_pool)

    first = await LeadOrchestrator(tmp_path).run_recon()
    first_call_count = worker.calls
    second = await LeadOrchestrator(tmp_path).run_recon()

    assert first_call_count > 0
    assert worker.calls == first_call_count
    assert any("reused cached worker result" in event for event in second.worker_events)
    assert first.findings == second.findings


@pytest.mark.asyncio
async def test_recon_fresh_bypasses_cached_worker_results(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _init_repo_memory(tmp_path)
    worker = CountingWorker()

    def fake_pool(config: SwainConfig, *, mock: bool = False) -> WorkerPool:
        pool = WorkerPool(max_concurrent=1, max_per_type=1)
        pool.register(worker)
        return pool

    monkeypatch.setattr("descry.orchestrator.lead.build_worker_pool", fake_pool)

    await LeadOrchestrator(tmp_path).run_recon()
    first_call_count = worker.calls
    await LeadOrchestrator(tmp_path).run_recon(use_cache=False)

    assert worker.calls == first_call_count * 2


def test_conversational_correction_persists_project_preference(
    tmp_path: Path,
) -> None:
    _init_repo_memory(tmp_path)

    LeadOrchestrator(tmp_path).record_correction("auth is handled upstream here")

    store = MemoryStore(tmp_path)
    preferences = store.read_yaml(tmp_path / ".swain" / "preferences.yaml")
    assert preferences["accepted_risk_patterns"][0]["note"] == (
        "auth is handled upstream here"
    )
    assert CoworkerMemory(store).preference_context_lines() == [
        "- accepted risk pattern: auth is handled upstream here"
    ]


def test_next_fix_falls_back_to_latest_finding_history(tmp_path: Path) -> None:
    _init_repo_memory(tmp_path)
    store = MemoryStore(tmp_path)
    finding = _finding(
        "sast.auth.python",
        Severity.HIGH,
        0.90,
        "Missing auth on tenant endpoint",
        network_exposed=True,
        requires_auth=False,
    )
    _save_history(store, "run123", [finding])

    assert LeadOrchestrator(tmp_path).next_fix_id() == finding.id


def _init_repo_memory(repo_root: Path) -> None:
    (repo_root / "requirements.txt").write_text("fastapi\n")
    (repo_root / "app.py").write_text("print('hello')\n")
    store = MemoryStore(repo_root)
    ProjectProfile(
        repo_name=repo_root.name,
        languages=["python"],
        frameworks=["fastapi"],
        deps=["fastapi"],
        has_auth=True,
    ).save(store)
    SwainConfig.completed(worker_mode="claude").save(store)


def _finding(
    rule: str,
    severity: Severity,
    confidence: float,
    title: str,
    *,
    network_exposed: bool = False,
    requires_auth: bool = True,
) -> Finding:
    return Finding(
        rule=rule,
        severity=severity,
        confidence=confidence,
        title=title,
        evidence=Evidence(file="backend/app/api/v1/tenants.py", anchor=title),
        exploitability=Exploitability(
            network_exposed=network_exposed,
            requires_auth=requires_auth,
        ),
        source=FindingSource(
            worker=WorkerType.CLAUDE,
            playbook=rule,
            playbook_version=1,
        ),
    )
