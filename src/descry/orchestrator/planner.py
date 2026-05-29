"""
Mission planner — decides WHAT to investigate based on:
- Trigger type (cron, PR, push, event, chat)
- Repo inventory (routes, deps, surfaces)
- Active schedule
- Risk events from inventory diff
- Applicable playbooks

Uses minimal tokens (no code reading here — that's the workers' job).
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from descry.models import Mission, Task, WorkerType
from descry.scanners.inventory import RepoInventory
from descry.playbooks.loader import PlaybookLoader
from descry.memory.scheduler import ScheduleStore


class Planner:
    def __init__(
        self,
        playbook_loader: PlaybookLoader,
        schedule_store: ScheduleStore,
    ) -> None:
        self.loader = playbook_loader
        self.schedule = schedule_store

    def plan(self, trigger: str, inventory: RepoInventory) -> Mission:
        mission_id = uuid.uuid4().hex[:12]
        all_playbooks = self.loader.load_all()
        applicable = self.loader.filter_applicable(all_playbooks, inventory)

        # Apply schedule filter for this trigger
        scheduled = self.schedule.get_schedules_for_trigger(trigger)
        scheduled_ids = {s["playbook"] for s in scheduled}

        # On PR/push: run scheduled + any triggered by risk events
        if trigger in ("on_pr", "on_commit"):
            active_pbs = [pb for pb in applicable if pb["id"] in scheduled_ids]
        else:
            # Full scan (cron/manual): run all applicable
            active_pbs = applicable

        # Escalate scans for detected risk events
        for event in inventory.risk_events:
            if event.startswith("new-auth-dep:"):
                self.schedule.upsert_risk_trigger(
                    "sast.auth",
                    paths=["**"],
                    reason=f"New auth dependency detected: {event.split(':')[1]}",
                )

        tasks = [self._make_task(pb, inventory) for pb in active_pbs]

        # Sort by priority (secrets first, then by severity signal)
        tasks.sort(key=lambda t: t.priority)

        return Mission(id=mission_id, trigger=trigger, tasks=tasks)

    def _make_task(self, playbook: dict[str, Any], inventory: RepoInventory) -> Task:
        worker = WorkerType(playbook.get("worker", "claude"))
        # Resolve applicable files from inventory
        files = self._resolve_files(playbook, inventory)
        priority = self._priority(playbook)
        return Task(
            id=uuid.uuid4().hex[:8],
            playbook_id=playbook["id"],
            worker=worker,
            files=files,
            priority=priority,
        )

    def _resolve_files(self, playbook: dict, inventory: RepoInventory) -> list[str]:
        include_globs = playbook.get("files", {}).get("include", ["**"])
        exclude_globs = playbook.get("files", {}).get("exclude", [])
        max_files = playbook.get("files", {}).get("max_files", 50)

        import fnmatch
        result = []
        for f in inventory.all_files:
            rel = str(f.relative_to(inventory.repo_root))
            if any(fnmatch.fnmatch(rel, g) for g in exclude_globs):
                continue
            if any(fnmatch.fnmatch(rel, g) for g in include_globs):
                result.append(rel)
            if len(result) >= max_files:
                break
        return result

    def _priority(self, playbook: dict) -> int:
        # Lower = higher priority
        priority_map = {
            "secrets": 1,
            "sast": 3,
            "deps": 4,
            "cloud": 5,
        }
        for prefix, p in priority_map.items():
            if playbook.get("id", "").startswith(prefix):
                return p
        return 5
