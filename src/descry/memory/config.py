"""User-facing Swain setup config."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from descry.memory.store import MemoryStore

VALID_WORKER_MODES = {"claude", "codex", "hybrid"}
VALID_CONCURRENCY = {"careful", "balanced", "fast"}

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
    concurrency: str = "careful"
    max_concurrent: int = 1
    max_per_type: int = 1

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

        mode = normalize_worker_mode(
            str(workers.get("mode") or data.get("worker_mode") or "hybrid")
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
            concurrency=concurrency,
            max_concurrent=max_concurrent,
            max_per_type=max_per_type,
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
        return model or "CLI default"

    def worker_summary(self) -> str:
        parts: list[str] = []
        if self.uses_claude:
            parts.append(f"Claude: {self.model_label('claude')}")
        if self.uses_codex:
            parts.append(f"Codex: {self.model_label('codex')}")
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
                    "model": self.claude_model,
                },
                "codex": {
                    "model": self.codex_model,
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


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default
