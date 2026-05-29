"""User-facing Swain setup config."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from descry.memory.store import MemoryStore

VALID_WORKER_MODES = {"claude", "codex", "hybrid"}
VALID_CONCURRENCY = {"careful", "balanced", "fast"}
VALID_WORKER_RUNTIMES = {"cli", "api"}

CONCURRENCY_PRESETS = {
    "careful": (1, 1),
    "balanced": (2, 2),
    "fast": (4, 4),
}


@dataclass(frozen=True)
class SwainConfig:
    setup_completed: bool = False
    worker_mode: str = "hybrid"
    claude_model: str = ""
    codex_model: str = ""
    claude_runtime: str = "cli"
    codex_runtime: str = "cli"
    claude_api_key_env: str = "ANTHROPIC_API_KEY"
    codex_api_key_env: str = "OPENAI_API_KEY"
    claude_api_base_url: str = "https://api.anthropic.com"
    codex_api_base_url: str = "https://api.openai.com/v1"
    concurrency: str = "careful"
    max_concurrent: int = 1
    max_per_type: int = 1
    api_max_output_tokens: int = 2048
    api_file_char_limit: int = 120_000

    @classmethod
    def load(cls, store: MemoryStore) -> SwainConfig:
        data = store.read_yaml(store.config_path)
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> SwainConfig:
        data = data or {}
        setup = _dict(data.get("setup"))
        workers = _dict(data.get("workers"))
        claude = _dict(workers.get("claude"))
        codex = _dict(workers.get("codex"))
        api = _dict(workers.get("api"))

        mode = normalize_worker_mode(
            str(workers.get("mode") or data.get("worker_mode") or "hybrid")
        )
        claude_runtime = normalize_worker_runtime(
            str(claude.get("runtime") or data.get("claude_runtime") or "cli")
        )
        codex_runtime = normalize_worker_runtime(
            str(codex.get("runtime") or data.get("codex_runtime") or "cli")
        )
        concurrency = normalize_concurrency(
            str(workers.get("concurrency") or data.get("concurrency") or "careful")
        )
        preset_max, preset_per_type = CONCURRENCY_PRESETS[concurrency]
        max_concurrent = _positive_int(workers.get("max_concurrent"), preset_max)
        max_per_type = _positive_int(workers.get("max_per_type"), preset_per_type)

        setup_done = setup.get("completed", data.get("setup_completed", False))
        return cls(
            setup_completed=bool(setup_done),
            worker_mode=mode,
            claude_model=str(claude.get("model") or data.get("claude_model") or ""),
            codex_model=str(codex.get("model") or data.get("codex_model") or ""),
            claude_runtime=claude_runtime,
            codex_runtime=codex_runtime,
            claude_api_key_env=str(
                claude.get("api_key_env")
                or data.get("claude_api_key_env")
                or "ANTHROPIC_API_KEY"
            ),
            codex_api_key_env=str(
                codex.get("api_key_env")
                or data.get("codex_api_key_env")
                or "OPENAI_API_KEY"
            ),
            claude_api_base_url=str(
                claude.get("api_base_url")
                or data.get("claude_api_base_url")
                or "https://api.anthropic.com"
            ).rstrip("/"),
            codex_api_base_url=str(
                codex.get("api_base_url")
                or data.get("codex_api_base_url")
                or "https://api.openai.com/v1"
            ).rstrip("/"),
            concurrency=concurrency,
            max_concurrent=max_concurrent,
            max_per_type=max_per_type,
            api_max_output_tokens=_positive_int(
                api.get("max_output_tokens"),
                _positive_int(data.get("api_max_output_tokens"), 2048),
            ),
            api_file_char_limit=_positive_int(
                api.get("file_char_limit"),
                _positive_int(data.get("api_file_char_limit"), 120_000),
            ),
        )

    @classmethod
    def completed(cls, **kwargs: Any) -> SwainConfig:
        data = {"setup_completed": True, **kwargs}
        return cls(**data)

    @property
    def uses_claude(self) -> bool:
        return self.worker_mode in {"claude", "hybrid"}

    @property
    def uses_codex(self) -> bool:
        return self.worker_mode in {"codex", "hybrid"}

    def model_label(self, worker: str) -> str:
        model = self.claude_model if worker == "claude" else self.codex_model
        runtime = self.claude_runtime if worker == "claude" else self.codex_runtime
        if model:
            return model
        return "CLI default" if runtime == "cli" else "API model not set"

    def runtime_label(self, worker: str) -> str:
        runtime = self.claude_runtime if worker == "claude" else self.codex_runtime
        return "CLI" if runtime == "cli" else "API"

    def worker_summary(self) -> str:
        parts: list[str] = []
        if self.uses_claude:
            parts.append(
                f"Claude {self.runtime_label('claude')}: {self.model_label('claude')}"
            )
        if self.uses_codex:
            parts.append(
                f"Codex {self.runtime_label('codex')}: {self.model_label('codex')}"
            )
        workers = ", ".join(parts) or "no model workers"
        return (
            f"{self.worker_mode} ({workers}); "
            f"{self.concurrency} concurrency, max {self.max_concurrent} at once"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "setup": {
                "completed": self.setup_completed,
            },
            "workers": {
                "mode": self.worker_mode,
                "concurrency": self.concurrency,
                "max_concurrent": self.max_concurrent,
                "max_per_type": self.max_per_type,
                "claude": {
                    "runtime": self.claude_runtime,
                    "model": self.claude_model,
                    "api_key_env": self.claude_api_key_env,
                    "api_base_url": self.claude_api_base_url,
                },
                "codex": {
                    "runtime": self.codex_runtime,
                    "model": self.codex_model,
                    "api_key_env": self.codex_api_key_env,
                    "api_base_url": self.codex_api_base_url,
                },
                "api": {
                    "max_output_tokens": self.api_max_output_tokens,
                    "file_char_limit": self.api_file_char_limit,
                },
            },
        }

    def save(self, store: MemoryStore) -> None:
        store.write_yaml(store.config_path, self.to_dict())


def setup_completed(repo_root: Path) -> bool:
    config_path = repo_root / ".swain" / "config.yaml"
    if not config_path.exists():
        return False
    try:
        data = yaml.safe_load(config_path.read_text()) or {}
        config = SwainConfig.from_dict(data)
    except (OSError, ValueError, yaml.YAMLError):
        return False
    return config.setup_completed


def normalize_worker_mode(value: str) -> str:
    mode = value.strip().lower()
    if mode not in VALID_WORKER_MODES:
        raise ValueError(
            f"worker mode must be one of {', '.join(sorted(VALID_WORKER_MODES))}"
        )
    return mode


def normalize_concurrency(value: str) -> str:
    concurrency = value.strip().lower()
    if concurrency not in VALID_CONCURRENCY:
        raise ValueError(
            f"concurrency must be one of {', '.join(sorted(VALID_CONCURRENCY))}"
        )
    return concurrency


def normalize_worker_runtime(value: str) -> str:
    runtime = value.strip().lower()
    if runtime not in VALID_WORKER_RUNTIMES:
        raise ValueError(
            f"worker runtime must be one of "
            f"{', '.join(sorted(VALID_WORKER_RUNTIMES))}"
        )
    return runtime


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default
