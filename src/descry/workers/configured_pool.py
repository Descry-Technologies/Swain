"""Build worker pools from saved Swain setup."""

from __future__ import annotations

from descry.memory.config import SwainConfig
from descry.orchestrator.pool import WorkerPool
from descry.workers.api_worker import AnthropicAPIWorker, OpenAIResponsesAPIWorker
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
        if config.claude_runtime == "api":
            pool.register(
                AnthropicAPIWorker(
                    model=config.claude_model,
                    api_key_env=config.claude_api_key_env,
                    api_base_url=config.claude_api_base_url,
                    max_output_tokens=config.api_max_output_tokens,
                    file_char_limit=config.api_file_char_limit,
                )
            )
        else:
            pool.register(ClaudeWorker(model=config.claude_model or None))
    if config.uses_codex:
        if config.codex_runtime == "api":
            pool.register(
                OpenAIResponsesAPIWorker(
                    model=config.codex_model,
                    api_key_env=config.codex_api_key_env,
                    api_base_url=config.codex_api_base_url,
                    max_output_tokens=config.api_max_output_tokens,
                    file_char_limit=config.api_file_char_limit,
                )
            )
        else:
            pool.register(CodexWorker(model=config.codex_model or None))
    return pool
