"""Build worker pools from saved Swain setup."""

from __future__ import annotations

from descry.memory.config import SwainConfig
from descry.orchestrator.pool import WorkerPool
from descry.workers.claude_worker import ClaudeWorker
from descry.workers.codex_worker import CodexWorker
from descry.workers.mock_worker import MockWorker


def build_worker_pool(config: SwainConfig, *, mock: bool = False) -> WorkerPool:
    pool = WorkerPool(
        max_concurrent=config.max_concurrent,
        max_per_type=config.max_per_type,
    )
    if mock:
        pool.register(MockWorker())
        return pool
    if config.uses_claude:
        pool.register(ClaudeWorker(model=config.claude_model or None))
    if config.uses_codex:
        pool.register(CodexWorker(model=config.codex_model or None))
    return pool
