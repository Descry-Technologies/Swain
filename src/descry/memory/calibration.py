"""
Per-rule calibration using Beta-Bernoulli model.
P(true_positive | rule, project) = (alpha + tp) / (alpha + beta + tp + fp)
Starting prior: alpha=beta=2 (weak, unbiased).
After N>=10 events, re-ranks displayed severity.
"""

from __future__ import annotations

import json
from pathlib import Path

from descry.memory.store import MemoryStore

PRIOR_ALPHA = 2.0
PRIOR_BETA = 2.0
MIN_EVENTS_TO_USE = 10


class CalibrationStore:
    def __init__(self, store: MemoryStore) -> None:
        self._store = store
        self._data: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        path = self._store.calibration_path
        if path.exists():
            self._data = json.loads(path.read_text())

    def _save(self) -> None:
        with self._store.lock():
            tmp = self._store.calibration_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._data, indent=2))
            tmp.replace(self._store.calibration_path)

    def record(self, rule: str, is_tp: bool) -> None:
        if rule not in self._data:
            self._data[rule] = {"tp": 0, "fp": 0}
        if is_tp:
            self._data[rule]["tp"] += 1
        else:
            self._data[rule]["fp"] += 1
        self._save()

    def precision(self, rule: str) -> float | None:
        d = self._data.get(rule)
        if not d:
            return None
        total = d["tp"] + d["fp"]
        if total < MIN_EVENTS_TO_USE:
            return None
        return (PRIOR_ALPHA + d["tp"]) / (PRIOR_ALPHA + PRIOR_BETA + total)

    def min_confidence(self) -> float:
        """Global minimum confidence threshold derived from calibration data."""
        all_precisions = [
            self.precision(r) for r in self._data
            if self.precision(r) is not None
        ]
        if not all_precisions:
            return 0.5  # default
        avg = sum(all_precisions) / len(all_precisions)
        # Don't go below 0.3 or above 0.9 from calibration alone
        return max(0.3, min(0.9, avg))
