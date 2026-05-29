from pathlib import Path

import pytest

from descry.memory.calibration import CalibrationStore
from descry.memory.conventions import ConventionStore
from descry.memory.profile import ProjectProfile
from descry.memory.store import MemoryStore
from descry.models import Task, WorkerReport, WorkerType
from descry.orchestrator.executor import Executor
from descry.orchestrator.pool import WorkerPool
from descry.playbooks.loader import PlaybookLoader
from descry.workers.base import WorkerResult


class RetryRecordingPool(WorkerPool):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[list[str]] = []

    async def run_task(
        self,
        task: Task,
        prompt: str,
        files: list[Path],
        repo_root: Path,
    ) -> WorkerResult:
        self.calls.append(task.files)
        if len(self.calls) == 1:
            return WorkerResult(report=None, timed_out=True, exit_code=-1)

        report = WorkerReport(
            task_id=task.id,
            worker=WorkerType.CLAUDE,
            playbook=task.playbook_id,
            playbook_version=1,
            findings=[],
        )
        return WorkerResult(report=report)


@pytest.mark.asyncio
async def test_executor_retries_timeouts_with_reduced_file_scope(
    tmp_path: Path,
) -> None:
    store = MemoryStore(tmp_path)
    pool = RetryRecordingPool()
    executor = Executor(
        pool,
        PlaybookLoader(tmp_path / "playbooks"),
        ProjectProfile(repo_name="demo"),
        ConventionStore(store),
        CalibrationStore(store),
        tmp_path,
    )
    task = Task(
        id="task-1",
        playbook_id="sast.auth.python",
        worker=WorkerType.CLAUDE,
        files=["a.py", "b.py", "c.py", "d.py"],
        context={"playbook_version": 1, "timeout_s": 10},
    )
    playbook = {
        "id": "sast.auth.python",
        "version": 1,
        "prompt": "Read files:\n{{file_list}}",
    }

    result = await executor._run_task(task, playbook)

    assert result.report is not None
    assert pool.calls == [
        ["a.py", "b.py", "c.py", "d.py"],
        ["a.py", "b.py"],
    ]
