from pathlib import Path

import pytest

from descry.commands.setup import run_setup
from descry.memory.config import SwainConfig, setup_completed
from descry.memory.store import MemoryStore
from descry.workers.api_worker import OpenAIResponsesAPIWorker
from descry.workers.claude_worker import ClaudeWorker
from descry.workers.codex_worker import CodexWorker
from descry.workers.configured_pool import build_worker_pool


def test_config_round_trips_setup_choices(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)
    config = SwainConfig.completed(
        worker_mode="codex",
        codex_model="custom-codex-model",
        concurrency="balanced",
        max_concurrent=2,
        max_per_type=1,
    )

    config.save(store)
    loaded = SwainConfig.load(store)

    assert setup_completed(tmp_path)
    assert loaded.worker_mode == "codex"
    assert loaded.uses_codex is True
    assert loaded.uses_claude is False
    assert loaded.codex_model == "custom-codex-model"
    assert "Codex CLI: custom-codex-model" in loaded.worker_summary()


def test_setup_completed_treats_invalid_config_as_incomplete(tmp_path: Path) -> None:
    config_path = tmp_path / ".swain" / "config.yaml"
    config_path.parent.mkdir()
    config_path.write_text("workers:\n  mode: nope\n")

    assert setup_completed(tmp_path) is False


def test_build_worker_pool_uses_configured_models() -> None:
    config = SwainConfig.completed(
        worker_mode="hybrid",
        claude_model="claude-security-model",
        codex_model="codex-security-model",
    )

    pool = build_worker_pool(config)

    claude = pool._workers[ClaudeWorker.worker_type]
    codex = pool._workers[CodexWorker.worker_type]
    assert isinstance(claude, ClaudeWorker)
    assert isinstance(codex, CodexWorker)
    assert claude.model == "claude-security-model"
    assert codex.model == "codex-security-model"


def test_build_worker_pool_can_use_codex_api_runtime() -> None:
    config = SwainConfig.completed(
        worker_mode="codex",
        codex_runtime="api",
        codex_model="gpt-test",
    )

    pool = build_worker_pool(config)

    worker = pool._workers[CodexWorker.worker_type]
    assert isinstance(worker, OpenAIResponsesAPIWorker)
    assert worker.model == "gpt-test"
    assert worker.api_key_env == "OPENAI_API_KEY"


@pytest.mark.asyncio
async def test_run_setup_can_use_noninteractive_defaults(tmp_path: Path) -> None:
    config = await run_setup(
        tmp_path,
        worker_mode="claude",
        claude_model="default",
        concurrency="careful",
        interactive=False,
        init_profile=False,
    )

    saved = SwainConfig.load(MemoryStore(tmp_path))

    assert config.setup_completed is True
    assert saved.worker_mode == "claude"
    assert saved.claude_model == ""
    assert saved.claude_runtime == "cli"
    assert saved.concurrency == "careful"
    assert not (tmp_path / ".swain" / "profile.yaml").exists()


@pytest.mark.asyncio
async def test_run_setup_can_configure_api_runtime(tmp_path: Path) -> None:
    await run_setup(
        tmp_path,
        worker_mode="codex",
        codex_runtime="api",
        codex_model="gpt-test",
        interactive=False,
        init_profile=False,
    )

    saved = SwainConfig.load(MemoryStore(tmp_path))
    assert saved.codex_runtime == "api"
    assert saved.codex_model == "gpt-test"
