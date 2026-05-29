"""Bounded worker pool — manages concurrent CLI subprocess workers."""

from __future__ import annotations

import asyncio
from typing import Callable

from descry.workers.base import BaseWorker, WorkerResult
from descry.models import Task, WorkerType


class WorkerPool:
    def __init__(self, max_concurrent: int = 4, max_per_type: int = 2) -> None:
        self._global_sem = asyncio.Semaphore(max_concurrent)
        self._type_sems: dict[WorkerType, asyncio.Semaphore] = {}
        self._max_per_type = max_per_type
        self._workers: dict[WorkerType, BaseWorker] = {}

    def register(self, worker: BaseWorker) -> None:
        self._workers[worker.worker_type] = worker
        self._type_sems[worker.worker_type] = asyncio.Semaphore(self._max_per_type)

    def get_worker(self, worker_type: WorkerType) -> BaseWorker | None:
        w = self._workers.get(worker_type)
        if w and w.is_available():
            return w
        # Fallback: if codex unavailable, use claude for fix gen too
        if worker_type == WorkerType.CODEX:
            return self._workers.get(WorkerType.CLAUDE)
        return None

    async def run_task(self, task: Task, prompt: str, files: list, repo_root) -> WorkerResult:
        worker = self.get_worker(task.worker)
        if worker is None:
            from descry.workers.mock_worker import MockWorker
            worker = MockWorker()

        type_sem = self._type_sems.get(worker.worker_type, asyncio.Semaphore(1))
        async with self._global_sem, type_sem:
            return await worker.run(task.id, prompt, files, repo_root)

    async def run_tasks_parallel(
        self,
        tasks: list[tuple[Task, str, list, object]],
        on_result: Callable[[Task, WorkerResult], None] | None = None,
    ) -> list[WorkerResult]:
        async def _run(task, prompt, files, repo_root):
            result = await self.run_task(task, prompt, files, repo_root)
            if on_result:
                on_result(task, result)
            return result

        return await asyncio.gather(*[_run(*args) for args in tasks])
