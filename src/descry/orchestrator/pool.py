"""Bounded worker pool — manages concurrent CLI subprocess workers."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from descry.models import Task, WorkerType
from descry.workers.base import BaseWorker, WorkerResult


class WorkerPool:
    def __init__(self, max_concurrent: int = 4, max_per_type: int = 2) -> None:
        self._global_sem = asyncio.Semaphore(max_concurrent)
        self._type_sems: dict[WorkerType, asyncio.Semaphore] = {}
        self._max_per_type = max_per_type
        self._workers: dict[WorkerType, BaseWorker] = {}
        self._disabled_workers: set[WorkerType] = set()
        self._timeout_strikes: dict[WorkerType, int] = {}

    def register(self, worker: BaseWorker) -> None:
        self._workers[worker.worker_type] = worker
        self._type_sems[worker.worker_type] = asyncio.Semaphore(self._max_per_type)

    def get_worker(self, worker_type: WorkerType) -> BaseWorker | None:
        workers = self._candidate_workers(worker_type)
        return workers[0] if workers else None

    async def run_task(
        self,
        task: Task,
        prompt: str,
        files: list,
        repo_root,
        on_event: Callable[[str], None] | None = None,
    ) -> WorkerResult:
        workers = self._candidate_workers(task.worker)
        if not workers:
            mock_worker = self._workers.get(WorkerType.MOCK)
            if mock_worker and mock_worker.is_available():
                if on_event:
                    on_event(f"{task.playbook_id}: using mock worker")
                workers = [mock_worker]
            else:
                if on_event:
                    on_event(
                        f"{task.playbook_id}: no {task.worker.value} worker "
                        "available"
                    )
                return WorkerResult(
                    report=None,
                    exit_code=127,
                    parse_error=f"No available {task.worker.value} worker",
                )

        last_result: WorkerResult | None = None
        for worker in workers:
            if worker.worker_type in self._disabled_workers:
                continue
            if on_event:
                on_event(
                    f"{task.playbook_id}: waiting for "
                    f"{worker.worker_type.value} subagent"
                )
            type_sem = self._type_sems.setdefault(
                worker.worker_type,
                asyncio.Semaphore(self._max_per_type),
            )
            async with self._global_sem, type_sem:
                if on_event:
                    on_event(
                        f"{task.playbook_id}: {worker.worker_type.value} "
                        f"reviewing {len(files)} file"
                        f"{'s' if len(files) != 1 else ''}"
                    )
                result = await worker.run(
                    task.id,
                    prompt,
                    files,
                    repo_root,
                    playbook_id=task.playbook_id,
                    playbook_version=int(task.context.get("playbook_version", 1)),
                    timeout_s=int(task.context.get("timeout_s", worker.timeout_s)),
                )
            if result.report is not None:
                if on_event:
                    finding_count = len(result.report.findings)
                    on_event(
                        f"{task.playbook_id}: {worker.worker_type.value} returned "
                        f"{finding_count} finding"
                        f"{'s' if finding_count != 1 else ''}"
                    )
                return result
            last_result = result
            if on_event:
                on_event(
                    f"{task.playbook_id}: {worker.worker_type.value} failed - "
                    f"{self._result_reason(result)}"
                )
            if self._should_disable_worker(result):
                self._disabled_workers.add(worker.worker_type)
                if on_event:
                    on_event(
                        f"{task.playbook_id}: disabled {worker.worker_type.value} "
                        "for this scan after an auth/quota diagnostic"
                    )
            elif result.timed_out:
                strikes = self._timeout_strikes.get(worker.worker_type, 0) + 1
                self._timeout_strikes[worker.worker_type] = strikes
                if strikes >= 2:
                    self._disabled_workers.add(worker.worker_type)
                    if on_event:
                        on_event(
                            f"{task.playbook_id}: disabled "
                            f"{worker.worker_type.value} for this scan after "
                            f"{strikes} timeouts"
                        )
            if not self._should_try_fallback(result):
                break

        if last_result is not None:
            return last_result
        return WorkerResult(
            report=None,
            exit_code=127,
            parse_error="No available worker",
        )

    def _result_reason(self, result: WorkerResult) -> str:
        if result.timed_out:
            return "timed out"
        if result.parse_error:
            return "returned output Swain could not parse"
        if result.exit_code != 0:
            diagnostic = (result.stderr or "").strip().splitlines()
            suffix = f": {diagnostic[0][:120]}" if diagnostic else ""
            return f"exit {result.exit_code}{suffix}"
        return "no report returned"

    def _candidate_workers(self, worker_type: WorkerType) -> list[BaseWorker]:
        order = [worker_type]
        if worker_type == WorkerType.CLAUDE:
            order.append(WorkerType.CODEX)
        elif worker_type == WorkerType.CODEX:
            order.append(WorkerType.CLAUDE)

        workers: list[BaseWorker] = []
        seen: set[WorkerType] = set()
        for candidate_type in order:
            if candidate_type in seen:
                continue
            seen.add(candidate_type)
            if candidate_type in self._disabled_workers:
                continue
            worker = self._workers.get(candidate_type)
            if worker and worker.is_available():
                workers.append(worker)
        return workers

    def _should_try_fallback(self, result: WorkerResult) -> bool:
        return result.report is None and (
            result.timed_out
            or bool(result.parse_error)
            or result.exit_code != 0
        )

    def _should_disable_worker(self, result: WorkerResult) -> bool:
        diagnostic = f"{result.parse_error}\n{result.stderr}".lower()
        return any(
            marker in diagnostic
            for marker in (
                "session limit",
                "quota",
                "rate limit",
                "not authenticated",
                "please authenticate",
                "log in",
                "login required",
                "api key missing",
                "invalid api key",
            )
        )

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
