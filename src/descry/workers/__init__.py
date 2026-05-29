"""Worker adapters — each wraps a CLI subprocess behind a stable interface."""

from descry.workers.base import BaseWorker, WorkerResult
from descry.workers.claude_worker import ClaudeWorker
from descry.workers.codex_worker import CodexWorker
from descry.workers.mock_worker import MockWorker

__all__ = [
    "BaseWorker",
    "WorkerResult",
    "ClaudeWorker",
    "CodexWorker",
    "MockWorker",
]
