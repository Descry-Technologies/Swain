"""
MemoryStore — top-level interface to .swain/ directory.

Layout:
  .swain/
    config.yaml          <- user-edited, committable
    profile.yaml         <- auto-learned project facts, committable
    conventions.yaml     <- accepted patterns, committable
    playbooks/           <- user + generated playbooks, committable
      generated/         <- pending review
      active/            <- promoted
    .local/              <- NEVER committed (gitignored)
      calibration.json   <- per-rule FP stats (sensitive)
      schedule.yaml      <- cron schedule
      history/           <- run summaries (may contain vuln details)
      feedback.jsonl     <- feedback log
      lock               <- file lock for concurrent writes
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml
from filelock import FileLock


class MemoryStore:
    def __init__(self, repo_root: Path) -> None:
        self.root = repo_root / ".swain"
        self.local = self.root / ".local"
        self._ensure_dirs()
        self._write_gitignore()

    def _ensure_dirs(self) -> None:
        for d in [
            self.root,
            self.root / "playbooks" / "generated",
            self.root / "playbooks" / "active",
            self.local,
            self.local / "history",
        ]:
            d.mkdir(parents=True, exist_ok=True)

    def _write_gitignore(self) -> None:
        gi = self.root / ".gitignore"
        if not gi.exists():
            gi.write_text(".local/\n")

    def lock(self) -> FileLock:
        return FileLock(str(self.local / "lock"))

    def read_yaml(self, path: Path) -> dict:
        if not path.exists():
            return {}
        with path.open() as f:
            return yaml.safe_load(f) or {}

    def write_yaml(self, path: Path, data: dict) -> None:
        tmp = path.with_suffix(".tmp")
        with tmp.open("w") as f:
            yaml.safe_dump(data, f, default_flow_style=False, allow_unicode=True)
        tmp.replace(path)

    def read_json(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def write_json(self, path: Path, data: dict[str, Any]) -> None:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True))
        tmp.replace(path)

    def append_jsonl(self, path: Path, record: dict) -> None:
        with path.open("a") as f:
            f.write(json.dumps(record) + "\n")

    @property
    def config_path(self) -> Path:
        return self.root / "config.yaml"

    @property
    def profile_path(self) -> Path:
        return self.root / "profile.yaml"

    @property
    def conventions_path(self) -> Path:
        return self.root / "conventions.yaml"

    @property
    def preferences_path(self) -> Path:
        return self.root / "preferences.yaml"

    @property
    def calibration_path(self) -> Path:
        return self.local / "calibration.json"

    @property
    def schedule_path(self) -> Path:
        return self.local / "schedule.yaml"

    @property
    def feedback_path(self) -> Path:
        return self.local / "feedback.jsonl"

    @property
    def history_dir(self) -> Path:
        return self.local / "history"

    @property
    def mission_ledger_path(self) -> Path:
        return self.local / "mission-ledger.json"

    @property
    def decision_log_path(self) -> Path:
        return self.local / "decision-log.jsonl"

    @property
    def fix_queue_path(self) -> Path:
        return self.local / "fix-queue.json"

    @property
    def watch_state_path(self) -> Path:
        return self.local / "watch-state.json"
