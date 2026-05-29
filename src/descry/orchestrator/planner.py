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

import fnmatch
import uuid
from typing import Any

from descry.memory.scheduler import ScheduleStore
from descry.models import Mission, Task, WorkerType
from descry.playbooks.loader import PlaybookLoader
from descry.scanners.inventory import RepoInventory

_ALWAYS_EXCLUDED_MODEL_FILES = (
    ".env",
    ".env.*",
    "**/.env",
    "**/.env.*",
    "**/*.key",
    "**/*.pem",
    "**/id_rsa",
    "**/id_dsa",
    "**/id_ecdsa",
    "**/id_ed25519",
)


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
            context={
                "playbook_version": playbook.get("version", 1),
                "timeout_s": playbook.get("timeout_s", 180),
            },
        )

    def _resolve_files(self, playbook: dict, inventory: RepoInventory) -> list[str]:
        include_globs = playbook.get("files", {}).get("include", ["**"])
        exclude_globs = playbook.get("files", {}).get("exclude", [])
        max_files = playbook.get("files", {}).get("max_files", 50)

        result: list[tuple[str, Any]] = []
        seen: set[str] = set()
        for glob in include_globs:
            for f in inventory.all_files:
                rel = str(f.relative_to(inventory.repo_root))
                if rel in seen:
                    continue
                if self._is_always_excluded_model_file(rel):
                    continue
                if any(fnmatch.fnmatch(rel, g) for g in exclude_globs):
                    continue
                if fnmatch.fnmatch(rel, glob):
                    result.append((rel, f))
                    seen.add(rel)
        playbook_id = playbook.get("id", "")
        result.sort(key=lambda item: self._file_rank(playbook_id, item[0], item[1]))
        return [path for path, _ in result[:max_files]]

    def _file_rank(
        self,
        playbook_id: str,
        path: str,
        source_path: Any | None = None,
    ) -> tuple[int, str]:
        path_lower = path.lower()
        content_lower = self._ranking_text(source_path)
        score = 0

        if any(part in path_lower for part in ("/api/", "/routes/", "/pages/api/")):
            score += 20
        if any(part in path_lower for part in ("/services/", "/controllers/")):
            score += 16
        if any(part in path_lower for part in ("/models/", "/schemas/", "/db/")):
            score += 10
        if path_lower.endswith((
            "config.py",
            "settings.py",
            "config.ts",
            "config.js",
        )):
            score += 12

        keyword_scores = self._keyword_scores(playbook_id)
        for keyword, weight in keyword_scores.items():
            if keyword in path_lower:
                score += weight * 2
            if keyword in content_lower:
                score += weight

        return (-score, path)

    def _ranking_text(self, source_path: Any | None) -> str:
        if source_path is None or not hasattr(source_path, "read_text"):
            return ""
        try:
            return source_path.read_text(errors="ignore")[:200_000].lower()
        except OSError:
            return ""

    def _is_always_excluded_model_file(self, path: str) -> bool:
        return any(
            fnmatch.fnmatch(path, pattern)
            for pattern in _ALWAYS_EXCLUDED_MODEL_FILES
        )

    def _keyword_scores(self, playbook_id: str) -> dict[str, int]:
        common = {
            "auth": 24,
            "tenant": 18,
            "user": 12,
            "admin": 10,
            "session": 10,
        }
        if playbook_id == "secrets.scan":
            return {
                **common,
                ".env": 30,
                "secret": 28,
                "key": 24,
                "credential": 24,
                "stripe": 20,
                "payment": 16,
                "config": 16,
                "settings": 16,
            }
        if "auth" in playbook_id:
            return {
                **common,
                "jwt": 20,
                "login": 18,
                "permission": 16,
                "role": 12,
                "password": 12,
            }
        if "payment" in playbook_id:
            return {
                "tenant": 10,
                "user": 8,
                "stripe": 28,
                "billing": 26,
                "payment": 24,
                "checkout": 20,
                "subscription": 18,
                "invoice": 16,
                "webhook": 16,
            }
        if "file-upload" in playbook_id:
            return {
                "tenant": 8,
                "user": 6,
                "upload": 28,
                "file": 18,
                "storage": 18,
                "media": 12,
                "attachment": 12,
            }
        if "tenant" in playbook_id:
            return {
                **common,
                "organization": 18,
                "workspace": 18,
                "membership": 16,
                "account": 12,
            }
        if "sql" in playbook_id:
            return {
                **common,
                "query": 24,
                "repository": 18,
                "database": 18,
                "sql": 18,
                "db": 12,
                "search": 10,
            }
        if "xss" in playbook_id:
            return {
                "html": 24,
                "markdown": 22,
                "preview": 18,
                "editor": 16,
                "render": 14,
                "component": 10,
                "page": 8,
            }
        return common

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
