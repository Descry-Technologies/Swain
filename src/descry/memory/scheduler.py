"""
Self-scheduling system — manages .swain/.local/schedule.yaml.
Recomputed after every 10 runs based on risk signals (NOT stored in git).

Risk signals (event-driven, not count-driven per GPT-5.5 critique):
  - new route added to codebase
  - new auth middleware detected
  - new payment-related dep
  - new env var reference
  - dependency updated/added
  - commit touching security-sensitive paths

Frequency tiers:
  on_commit   — every push to monitored branches
  on_pr       — every PR open/update
  daily       — once per day
  weekly      — once per week
  monthly     — once per month
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from descry.memory.store import MemoryStore

DEFAULT_SCHEDULE: list[dict[str, Any]] = [
    {
        "playbook": "secrets.scan",
        "trigger": "on_commit",
        "paths": ["**"],
        "reason": "Secret leaks need immediate detection on every push",
    },
    {
        "playbook": "deps.osv-scan",
        "trigger": "daily",
        "paths": ["**/package.json", "**/pyproject.toml", "**/Cargo.toml", "**/go.mod"],
        "reason": "New CVEs published daily",
    },
    {
        "playbook": "sast.xss.react",
        "trigger": "on_pr",
        "paths": ["**/*.tsx", "**/*.jsx", "**/*.ts", "**/*.js"],
        "reason": "Default: review XSS on every PR",
    },
    {
        "playbook": "sast.sql-injection",
        "trigger": "on_pr",
        "paths": ["**"],
        "reason": "Default: review SQL injection on every PR",
    },
]


class ScheduleStore:
    def __init__(self, store: MemoryStore) -> None:
        self._store = store
        self._data: dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        self._data = self._store.read_yaml(self._store.schedule_path)
        if "schedules" not in self._data:
            self._data = {
                "generated_at": datetime.now(UTC).isoformat(),
                "runs_since_last_recompute": 0,
                "schedules": DEFAULT_SCHEDULE,
            }
            self._save()

    def _save(self) -> None:
        with self._store.lock():
            self._store.write_yaml(self._store.schedule_path, self._data)

    def get_schedules_for_trigger(self, trigger: str) -> list[dict]:
        return [
            s for s in self._data.get("schedules", [])
            if s.get("trigger") == trigger
        ]

    def increment_run_count(self) -> int:
        self._data["runs_since_last_recompute"] = (
            self._data.get("runs_since_last_recompute", 0) + 1
        )
        self._save()
        return self._data["runs_since_last_recompute"]

    def needs_recompute(self) -> bool:
        return self._data.get("runs_since_last_recompute", 0) >= 10

    def apply_recompute(self, new_schedules: list[dict]) -> None:
        self._data["schedules"] = new_schedules
        self._data["runs_since_last_recompute"] = 0
        self._data["generated_at"] = datetime.now(UTC).isoformat()
        self._save()

    def upsert_risk_trigger(self, playbook: str, paths: list[str], reason: str) -> None:
        """Called when a risk event is detected (new route, new auth dep, etc.)."""
        schedules = self._data.get("schedules", [])
        existing = next((s for s in schedules if s["playbook"] == playbook), None)
        if existing:
            if existing.get("trigger") in ("monthly", "weekly"):
                existing["trigger"] = "on_commit"
                existing["paths"] = paths
                existing["reason"] = reason
                existing["escalated_at"] = datetime.now(UTC).isoformat()
        else:
            schedules.append({
                "playbook": playbook,
                "trigger": "on_commit",
                "paths": paths,
                "reason": reason,
            })
        self._save()
