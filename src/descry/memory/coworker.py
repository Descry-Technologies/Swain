"""Coworker memory for Swain's lead-orchestrator layer."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from descry.memory.store import MemoryStore


class MissionPhase(StrEnum):
    IDLE = "idle"
    RECON = "recon"
    REVIEW = "review"
    FIX_QUEUE = "fix_queue"
    WATCH = "watch"
    DONE = "done"
    BLOCKED = "blocked"


class MissionKind(StrEnum):
    RECON = "recon"
    REVIEW = "review"
    FIX_QUEUE = "fix_queue"
    WATCH = "watch"


class DecisionLevel(StrEnum):
    INFO = "info"
    WARNING = "warning"
    BLOCKER = "blocker"


class LeadIntent(BaseModel):
    action: str
    mission_type: MissionKind | None = None
    finding_id: str = ""
    feedback_action: str = ""
    launch_focus: bool = False
    text: str = ""


class DelegatedTaskRecord(BaseModel):
    task_id: str
    playbook_id: str
    worker: str
    status: str = "queued"
    finding_count: int = 0
    warning: str = ""


class MissionLedger(BaseModel):
    active_objective: str = ""
    mission_id: str = ""
    mission_type: MissionKind = MissionKind.RECON
    phase: MissionPhase = MissionPhase.IDLE
    trigger: str = ""
    started_at: str | None = None
    updated_at: str | None = None
    delegated_tasks: list[DelegatedTaskRecord] = Field(default_factory=list)
    worker_warnings: list[str] = Field(default_factory=list)
    latest_decision_ids: list[str] = Field(default_factory=list)
    latest_summary: str = ""


class DecisionRecord(BaseModel):
    id: str
    timestamp: str
    mission_id: str = ""
    level: DecisionLevel = DecisionLevel.INFO
    summary: str
    rationale: str = ""
    trusted: bool = True
    next_step: str = ""


class FixQueueItem(BaseModel):
    id: str
    finding_id: str
    title: str
    severity: str
    confidence: float
    exposure: str
    launch_risk: bool = False
    file: str
    line: int | None = None
    score: float
    rationale: str
    status: str = "queued"


class WatchState(BaseModel):
    enabled: bool = False
    repo_path: str = ""
    service_name: str = ""
    interval_s: int = 30
    last_git_signature: str = ""
    last_triggered_at: str | None = None
    last_trigger_reason: str = ""
    last_scan_mission_id: str = ""
    installed_service_path: str = ""
    pid: int | None = None
    updated_at: str = Field(default_factory=lambda: _utc_now())


class CoworkerMemory:
    """Reads and writes the local state that makes Swain act like a coworker."""

    def __init__(self, store: MemoryStore) -> None:
        self.store = store

    def load_ledger(self) -> MissionLedger:
        return MissionLedger.model_validate(self.store.read_json(
            self.store.mission_ledger_path,
        ))

    def save_ledger(self, ledger: MissionLedger) -> None:
        ledger.updated_at = _utc_now()
        self.store.write_json(
            self.store.mission_ledger_path,
            ledger.model_dump(mode="json"),
        )

    def start_mission(
        self,
        *,
        objective: str,
        mission_type: MissionKind,
        trigger: str,
    ) -> MissionLedger:
        now = _utc_now()
        ledger = MissionLedger(
            active_objective=objective,
            mission_type=mission_type,
            phase=MissionPhase.RECON,
            trigger=trigger,
            started_at=now,
            updated_at=now,
        )
        self.save_ledger(ledger)
        return ledger

    def complete_mission(
        self,
        ledger: MissionLedger,
        *,
        phase: MissionPhase = MissionPhase.DONE,
        summary: str = "",
        warnings: list[str] | None = None,
    ) -> None:
        current = self.load_ledger()
        if current.latest_decision_ids:
            merged_ids: list[str] = []
            for decision_id in [
                *current.latest_decision_ids,
                *ledger.latest_decision_ids,
            ]:
                if decision_id not in merged_ids:
                    merged_ids.append(decision_id)
            ledger.latest_decision_ids = merged_ids[:20]
        ledger.phase = phase
        if summary:
            ledger.latest_summary = summary
        if warnings is not None:
            ledger.worker_warnings = list(warnings)
        self.save_ledger(ledger)

    def append_decision(
        self,
        *,
        summary: str,
        mission_id: str = "",
        level: DecisionLevel = DecisionLevel.INFO,
        rationale: str = "",
        trusted: bool = True,
        next_step: str = "",
    ) -> DecisionRecord:
        timestamp = _utc_now()
        decision = DecisionRecord(
            id=_short_hash(f"{timestamp}:{mission_id}:{summary}"),
            timestamp=timestamp,
            mission_id=mission_id,
            level=level,
            summary=summary,
            rationale=rationale,
            trusted=trusted,
            next_step=next_step,
        )
        self.store.append_jsonl(
            self.store.decision_log_path,
            decision.model_dump(mode="json"),
        )
        ledger = self.load_ledger()
        ledger.latest_decision_ids = [decision.id, *ledger.latest_decision_ids[:19]]
        self.save_ledger(ledger)
        return decision

    def recent_decisions(self, limit: int = 8) -> list[DecisionRecord]:
        path = self.store.decision_log_path
        if not path.exists():
            return []
        rows: list[DecisionRecord] = []
        try:
            lines = path.read_text().splitlines()
        except OSError:
            return []
        for line in reversed(lines):
            if not line.strip():
                continue
            try:
                rows.append(DecisionRecord.model_validate(json.loads(line)))
            except (json.JSONDecodeError, ValueError):
                continue
            if len(rows) >= limit:
                break
        return rows

    def save_fix_queue(self, items: list[FixQueueItem]) -> None:
        self.store.write_json(
            self.store.fix_queue_path,
            {
                "updated_at": _utc_now(),
                "items": [item.model_dump(mode="json") for item in items],
            },
        )

    def load_fix_queue(self) -> list[FixQueueItem]:
        data = self.store.read_json(self.store.fix_queue_path)
        raw_items = data.get("items", [])
        if not isinstance(raw_items, list):
            return []
        items: list[FixQueueItem] = []
        for raw_item in raw_items:
            if not isinstance(raw_item, dict):
                continue
            try:
                items.append(FixQueueItem.model_validate(raw_item))
            except ValueError:
                continue
        return items

    def next_fix(self) -> FixQueueItem | None:
        return next(
            (item for item in self.load_fix_queue() if item.status == "queued"),
            None,
        )

    def load_watch_state(self) -> WatchState:
        return WatchState.model_validate(self.store.read_json(
            self.store.watch_state_path,
        ))

    def save_watch_state(self, state: WatchState) -> None:
        state.updated_at = _utc_now()
        self.store.write_json(
            self.store.watch_state_path,
            state.model_dump(mode="json"),
        )

    def record_preference(self, *, kind: str, note: str) -> dict[str, Any]:
        data = self.store.read_yaml(self.store.preferences_path)
        preferences = _normalize_preferences(data)
        entry = {
            "id": _short_hash(note),
            "note": note,
            "created_at": _utc_now(),
        }
        preferences.setdefault(kind, [])
        if not any(item.get("id") == entry["id"] for item in preferences[kind]):
            preferences[kind].append(entry)
        self.store.write_yaml(self.store.preferences_path, preferences)
        return entry

    def preference_context_lines(self) -> list[str]:
        preferences = _normalize_preferences(
            self.store.read_yaml(self.store.preferences_path)
        )
        lines: list[str] = []
        labels = {
            "launch_blockers": "launch blocker",
            "accepted_risk_patterns": "accepted risk pattern",
            "stack_notes": "stack note",
            "fix_style_preferences": "fix style",
        }
        for key, label in labels.items():
            for item in preferences.get(key, [])[:5]:
                note = str(item.get("note") or "").strip()
                if note:
                    lines.append(f"- {label}: {note}")
        return lines[:20]


def _normalize_preferences(data: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    normalized: dict[str, list[dict[str, Any]]] = {}
    for key in (
        "launch_blockers",
        "accepted_risk_patterns",
        "stack_notes",
        "fix_style_preferences",
    ):
        value = data.get(key, [])
        normalized[key] = value if isinstance(value, list) else []
    return normalized


def _short_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:12]


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()
