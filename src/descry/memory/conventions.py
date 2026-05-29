"""
Convention store — patterns the agent has learned are acceptable in this codebase.

Promotion algorithm:
- Same rule fires on similar code N≥3 times
- Marked FP at least 2 of those times (different events or 7-day spread)
- 7-day cooling period since first observation
- High-severity rules (critical/high) CANNOT be auto-promoted — require explicit config.yaml entry
- Each convention stores full provenance so it can be revoked
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from descry.memory.store import MemoryStore

PROMOTION_MIN_OCCURRENCES = 3
PROMOTION_MIN_FPS = 2
PROMOTION_COOLING_DAYS = 7
AUTO_PROMOTE_MAX_SEVERITY = "medium"  # critical/high never auto-promoted


class ConventionStore:
    def __init__(self, store: MemoryStore) -> None:
        self._store = store
        self._data: dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        self._data = self._store.read_yaml(self._store.conventions_path)
        if "conventions" not in self._data:
            self._data["conventions"] = {}
        if "candidates" not in self._data:
            self._data["candidates"] = {}

    def _save(self) -> None:
        with self._store.lock():
            self._store.write_yaml(self._store.conventions_path, self._data)

    def record_fp(self, finding_id: str, rule: str, file_glob: str, severity: str) -> None:
        """Record an FP event and attempt to promote to convention."""
        candidates = self._data["candidates"]
        key = f"{rule}:{file_glob}"
        if key not in candidates:
            candidates[key] = {
                "rule": rule,
                "file_glob": file_glob,
                "severity": severity,
                "occurrences": 0,
                "fp_events": [],
                "first_seen": datetime.utcnow().isoformat(),
            }
        c = candidates[key]
        c["occurrences"] += 1
        c["fp_events"].append({"finding_id": finding_id, "ts": datetime.utcnow().isoformat()})
        self._maybe_promote(key, c)
        self._save()

    def _maybe_promote(self, key: str, candidate: dict) -> None:
        severity = candidate.get("severity", "low")
        if severity in ("critical", "high"):
            return  # never auto-promote

        fps = candidate.get("fp_events", [])
        occurrences = candidate.get("occurrences", 0)
        if occurrences < PROMOTION_MIN_OCCURRENCES:
            return
        if len(fps) < PROMOTION_MIN_FPS:
            return

        first_seen = datetime.fromisoformat(candidate["first_seen"])
        if datetime.utcnow() - first_seen < timedelta(days=PROMOTION_COOLING_DAYS):
            return

        # Promote
        convention_id = key.replace(":", "__")
        self._data["conventions"][convention_id] = {
            "rule": candidate["rule"],
            "file_glob": candidate["file_glob"],
            "severity": severity,
            "promoted_at": datetime.utcnow().isoformat(),
            "provenance": {"fp_events": fps, "occurrences": occurrences},
            "active": True,
        }
        del self._data["candidates"][key]

    def get_active_conventions(self, rule: str | None = None) -> list[dict]:
        return [
            c for c in self._data["conventions"].values()
            if c.get("active") and (rule is None or c["rule"] == rule)
        ]

    def revoke(self, convention_id: str, reason: str = "") -> None:
        if convention_id in self._data["conventions"]:
            self._data["conventions"][convention_id]["active"] = False
            self._data["conventions"][convention_id]["revoked_reason"] = reason
            self._save()

    def to_context_lines(self) -> list[str]:
        active = self.get_active_conventions()
        return [f"- {c['rule']} in {c['file_glob']}" for c in active[:10]]
