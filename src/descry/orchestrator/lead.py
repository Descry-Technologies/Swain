"""Lead orchestrator for Swain's coworker workflow."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from descry.commands.history import load_latest_findings
from descry.memory.calibration import CalibrationStore
from descry.memory.config import SwainConfig
from descry.memory.conventions import ConventionStore
from descry.memory.coworker import (
    CoworkerMemory,
    DecisionLevel,
    DecisionRecord,
    DelegatedTaskRecord,
    FixQueueItem,
    LeadIntent,
    MissionKind,
    MissionLedger,
    MissionPhase,
    WatchState,
)
from descry.memory.profile import ProjectProfile
from descry.memory.scheduler import ScheduleStore
from descry.memory.store import MemoryStore
from descry.models import Finding, Severity
from descry.orchestrator.executor import Executor
from descry.orchestrator.planner import Planner
from descry.playbooks.loader import PlaybookLoader
from descry.resources import builtin_playbooks_dir
from descry.scanners.inventory import RepoInventory
from descry.scanners.secrets import SecretHit, SecretsScanner
from descry.workers.configured_pool import build_worker_pool

_SEVERITY_SCORE = {
    Severity.CRITICAL.value: 100,
    Severity.HIGH.value: 80,
    Severity.MEDIUM.value: 50,
    Severity.LOW.value: 20,
    Severity.INFO.value: 5,
}

_LAUNCH_RISK_MARKERS = (
    "auth",
    "billing",
    "checkout",
    "credential",
    "csrf",
    "file-upload",
    "jwt",
    "login",
    "password",
    "payment",
    "secret",
    "sql",
    "stripe",
    "tenant",
    "upload",
    "xss",
)


class LeadOrchestrationError(RuntimeError):
    """Raised when the lead workflow cannot start safely."""


class LeadStatusSnapshot(BaseModel):
    ledger: MissionLedger
    decisions: list[DecisionRecord]
    fix_queue: list[FixQueueItem]
    watch_state: WatchState


@dataclass(frozen=True)
class LeadRunResult:
    mission_id: str
    findings: list[Finding]
    secret_hits: list[SecretHit]
    warnings: list[str]
    decisions: list[DecisionRecord]
    fix_queue: list[FixQueueItem]
    worker_events: list[str] = field(default_factory=list)


class LeadOrchestrator:
    """Conversational lead over the deterministic planner/executor core."""

    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root.resolve()

    def interpret(self, text: str) -> LeadIntent:
        stripped = text.strip()
        lowered = stripped.lower()
        finding_id = self._extract_finding_id(stripped)

        if not lowered:
            return LeadIntent(action="unknown", text=stripped)

        if self._asks_for_worker_details(lowered):
            return LeadIntent(action="details", text=stripped)

        if self._asks_for_watch(lowered):
            return LeadIntent(
                action="watch",
                mission_type=MissionKind.WATCH,
                text=stripped,
            )

        if self._asks_for_status(lowered):
            return LeadIntent(action="status", text=stripped)

        if self._asks_for_patch_draft(lowered):
            return LeadIntent(
                action="draft_fix",
                mission_type=MissionKind.FIX_QUEUE,
                finding_id=finding_id,
                text=stripped,
            )

        if self._is_correction(lowered):
            return LeadIntent(action="record_preference", text=stripped)

        if self._asks_for_recon(lowered):
            launch_focus = any(
                marker in lowered
                for marker in ("launch", "release", "ship", "blocker", "blocks")
            )
            return LeadIntent(
                action="scan",
                mission_type=MissionKind.RECON,
                launch_focus=launch_focus,
                text=stripped,
            )

        return LeadIntent(action="unknown", text=stripped)

    async def run_recon(
        self,
        *,
        trigger: str = "manual",
        objective: str = "",
        launch_focus: bool = False,
        mock: bool = False,
        persist: bool = True,
        on_event: Callable[[str], None] | None = None,
    ) -> LeadRunResult:
        profile_path = self.repo_root / ".swain" / "profile.yaml"
        if not profile_path.exists():
            raise LeadOrchestrationError(
                "No .swain/profile.yaml found. Run swain setup first."
            )

        store = MemoryStore(self.repo_root)
        coworker = CoworkerMemory(store)
        events: list[str] = []
        decisions: list[DecisionRecord] = []
        objective_text = objective or (
            "scan this repo and tell me what blocks launch"
            if launch_focus
            else "scan this repo"
        )
        if persist:
            ledger = coworker.start_mission(
                objective=objective_text,
                mission_type=MissionKind.RECON,
                trigger=trigger,
            )
        else:
            now = datetime.now(UTC).isoformat()
            ledger = MissionLedger(
                active_objective=objective_text,
                mission_type=MissionKind.RECON,
                phase=MissionPhase.RECON,
                trigger=trigger,
                started_at=now,
                updated_at=now,
            )

        def emit(event: str) -> None:
            events.append(event)
            if on_event:
                on_event(event)

        def decide(
            summary: str,
            *,
            level: DecisionLevel = DecisionLevel.INFO,
            rationale: str = "",
            trusted: bool = True,
            next_step: str = "",
        ) -> DecisionRecord:
            if persist:
                decision = coworker.append_decision(
                    summary=summary,
                    mission_id=ledger.mission_id,
                    level=level,
                    rationale=rationale,
                    trusted=trusted,
                    next_step=next_step,
                )
            else:
                decision = _decision_record(
                    summary=summary,
                    mission_id=ledger.mission_id,
                    level=level,
                    rationale=rationale,
                    trusted=trusted,
                    next_step=next_step,
                )
            decisions.append(decision)
            return decision

        profile = ProjectProfile.load(store)
        conventions = ConventionStore(store)
        calibration = CalibrationStore(store)
        schedule = ScheduleStore(store, persist_defaults=persist)

        emit("indexing repo and detecting risky surfaces")
        inventory = RepoInventory.scan(self.repo_root, prev_deps=profile.deps)
        stack = ", ".join(inventory.frameworks or inventory.languages) or "unknown"
        emit(f"repo profile: {len(inventory.all_files)} files, stack={stack}")
        decide(
            "Mapped repository surfaces",
            rationale=(
                f"Inventory found {len(inventory.all_files)} files and "
                f"stack={stack}."
            ),
        )

        emit("running local secret sweep before model workers")
        secret_hits = await SecretsScanner().run(self.repo_root)
        emit(
            f"local secret sweep returned {len(secret_hits)} hit"
            f"{'s' if len(secret_hits) != 1 else ''}"
        )
        if secret_hits:
            decide(
                "Static secret sweep found possible launch blockers",
                level=DecisionLevel.BLOCKER,
                rationale=(
                    f"{len(secret_hits)} potential secret hit"
                    f"{'s' if len(secret_hits) != 1 else ''} found before "
                    "model review."
                ),
                next_step="Review and rotate any real secret before release.",
            )

        config = SwainConfig.load(store)
        emit(
            "worker setup: mock offline demo"
            if mock else f"worker setup: {config.worker_summary()}"
        )
        pool = build_worker_pool(config, mock=mock)

        loader = PlaybookLoader(
            builtin_dir=builtin_playbooks_dir(),
            user_dir=store.root / "playbooks",
        )
        mission = Planner(loader, schedule).plan(trigger, inventory)
        if persist:
            ledger.latest_decision_ids = coworker.load_ledger().latest_decision_ids
        ledger.mission_id = mission.id
        ledger.delegated_tasks = [
            DelegatedTaskRecord(
                task_id=task.id,
                playbook_id=task.playbook_id,
                worker=task.worker.value,
            )
            for task in mission.tasks
        ]
        if persist:
            coworker.save_ledger(ledger)

        task_names = ", ".join(task.playbook_id for task in mission.tasks)
        file_count = sum(len(task.files) for task in mission.tasks)
        emit(
            f"planned {len(mission.tasks)} model playbook"
            f"{'s' if len(mission.tasks) != 1 else ''} over {file_count} "
            f"file reference{'s' if file_count != 1 else ''}"
        )
        emit(f"queue: {task_names or 'empty'}")
        emit(
            "model workers can spend Claude/Codex quota; worker calls are shown below"
        )
        decide(
            "Queued bounded worker review",
            rationale=(
                f"{len(mission.tasks)} playbook"
                f"{'s' if len(mission.tasks) != 1 else ''}; "
                f"{file_count} file reference"
                f"{'s' if file_count != 1 else ''}. Concurrency follows "
                f"the saved {config.concurrency} quota profile."
            ),
        )

        executor = Executor(
            pool,
            loader,
            profile,
            conventions,
            calibration,
            self.repo_root,
        )
        findings = await executor.execute(mission, on_event=emit)
        warnings = list(executor.task_warnings)
        if persist:
            _save_history(store, mission.id, findings, mock=mock)

            schedule.increment_run_count()
            if schedule.needs_recompute():
                schedule.apply_recompute(schedule._data.get("schedules", []))

        fix_queue = self.build_fix_queue(findings)
        if persist:
            coworker.save_fix_queue(fix_queue)

        if warnings:
            for warning in warnings[:6]:
                decide(
                    "Worker result needs attention",
                    level=DecisionLevel.WARNING,
                    rationale=warning,
                    trusted=False,
                    next_step=(
                        "Run swain doctor --probe-workers, then rerun the scan."
                    ),
                )
            if self._has_repeated_timeouts(warnings, events):
                decide(
                    "Stopped trusting timed-out worker delegation",
                    level=DecisionLevel.WARNING,
                    rationale=(
                        "Repeated worker timeouts mean more delegation would "
                        "spend quota without improving confidence."
                    ),
                    trusted=False,
                )

        if fix_queue:
            first = fix_queue[0]
            decide(
                "Built an ordered fix queue",
                level=(
                    DecisionLevel.BLOCKER
                    if first.severity in {"critical", "high"} and first.launch_risk
                    else DecisionLevel.INFO
                ),
                rationale=(
                    f"{len(fix_queue)} queued finding"
                    f"{'s' if len(fix_queue) != 1 else ''}. First: "
                    f"{first.finding_id[:8]} ({first.rationale})."
                ),
                next_step=f"Draft a patch with swain fix {first.finding_id[:8]}.",
            )
            phase = MissionPhase.FIX_QUEUE
            summary = f"{len(fix_queue)} finding(s) queued for reviewable fixes"
        elif warnings:
            phase = MissionPhase.BLOCKED
            summary = "Scan incomplete; worker warnings need attention"
        elif secret_hits:
            phase = MissionPhase.REVIEW
            summary = "Static secret hits need manual review"
        else:
            decide(
                "No launch blockers found in completed checks",
                rationale="Recon completed without findings or static secret hits.",
            )
            phase = MissionPhase.DONE
            summary = "No findings returned by completed checks"

        if persist:
            coworker.complete_mission(
                ledger,
                phase=phase,
                summary=summary,
                warnings=warnings,
            )

        return LeadRunResult(
            mission_id=mission.id,
            findings=findings,
            secret_hits=secret_hits,
            warnings=warnings,
            decisions=decisions,
            fix_queue=fix_queue,
            worker_events=events,
        )

    def build_fix_queue(self, findings: list[Finding]) -> list[FixQueueItem]:
        items = [self._queue_item(finding) for finding in findings]
        return sorted(
            items,
            key=lambda item: (-item.score, item.title.lower(), item.finding_id),
        )

    def status_snapshot(self) -> LeadStatusSnapshot:
        store = MemoryStore(self.repo_root)
        coworker = CoworkerMemory(store)
        fix_queue = coworker.load_fix_queue()
        if not fix_queue:
            fix_queue = self.build_fix_queue_from_history(store)
        return LeadStatusSnapshot(
            ledger=coworker.load_ledger(),
            decisions=coworker.recent_decisions(),
            fix_queue=fix_queue,
            watch_state=coworker.load_watch_state(),
        )

    def next_fix_id(self) -> str:
        store = MemoryStore(self.repo_root)
        coworker = CoworkerMemory(store)
        next_item = coworker.next_fix()
        if next_item is None:
            history_queue = self.build_fix_queue_from_history(store)
            next_item = history_queue[0] if history_queue else None
        return next_item.finding_id if next_item else ""

    def build_fix_queue_from_history(self, store: MemoryStore) -> list[FixQueueItem]:
        findings: list[Finding] = []
        for raw_finding in load_latest_findings(store):
            if raw_finding.get("lifecycle", {}).get("status", "open") != "open":
                continue
            try:
                findings.append(Finding.model_validate(raw_finding))
            except ValueError:
                continue
        return self.build_fix_queue(findings)

    def record_correction(self, text: str) -> DecisionRecord:
        store = MemoryStore(self.repo_root)
        coworker = CoworkerMemory(store)
        kind = (
            "launch_blockers"
            if "blocker" in text.lower()
            else "accepted_risk_patterns"
        )
        coworker.record_preference(kind=kind, note=text)
        return coworker.append_decision(
            summary="Learned a conversational correction",
            level=DecisionLevel.INFO,
            rationale=text,
            next_step="Future scans will include this note as project preference.",
        )

    def enable_watch(
        self,
        *,
        interval_s: int = 30,
        service_name: str = "",
    ) -> WatchState:
        store = MemoryStore(self.repo_root)
        coworker = CoworkerMemory(store)
        state = coworker.load_watch_state()
        state.enabled = True
        state.repo_path = str(self.repo_root)
        state.interval_s = interval_s
        if service_name:
            state.service_name = service_name
        coworker.save_watch_state(state)
        coworker.append_decision(
            summary="Enabled repository watch",
            level=DecisionLevel.INFO,
            rationale=(
                "Swain will poll git commit and tracked-file state for changes."
            ),
            next_step=f"Run swain watch {self.repo_root} to keep it active.",
        )
        return state

    def _queue_item(self, finding: Finding) -> FixQueueItem:
        severity = finding.severity.value
        launch_risk = self._is_launch_risk(finding)
        exposure_score, exposure = self._exposure_score(finding)
        score = (
            _SEVERITY_SCORE.get(severity, 0)
            + finding.confidence * 10
            + exposure_score
            + (15 if launch_risk else 0)
        )
        file = finding.evidence.file
        line = finding.evidence.line_start
        reasons = [
            severity,
            f"{finding.confidence:.0%} confidence",
            exposure,
        ]
        if launch_risk:
            reasons.append("launch-risk surface")
        return FixQueueItem(
            id=finding.id[:8],
            finding_id=finding.id,
            title=finding.title,
            severity=severity,
            confidence=finding.confidence,
            exposure=exposure,
            launch_risk=launch_risk,
            file=file,
            line=line,
            score=round(score, 2),
            rationale=", ".join(reasons),
        )

    def _exposure_score(self, finding: Finding) -> tuple[int, str]:
        exploitability = finding.exploitability
        if exploitability.network_exposed and not exploitability.requires_auth:
            return 30, "network-exposed without auth"
        if exploitability.network_exposed:
            return 18, "network-exposed"
        if not exploitability.requires_auth:
            return 10, "no auth required"
        return 0, "local or authenticated"

    def _is_launch_risk(self, finding: Finding) -> bool:
        haystack = " ".join(
            [
                finding.rule,
                finding.title,
                finding.description,
                finding.evidence.file,
                finding.remediation.summary,
            ]
        ).lower()
        return any(marker in haystack for marker in _LAUNCH_RISK_MARKERS)

    def _extract_finding_id(self, text: str) -> str:
        match = re.search(r"\b[0-9a-fA-F]{6,16}\b", text)
        return match.group(0) if match else ""

    def _asks_for_worker_details(self, lowered: str) -> bool:
        return any(
            phrase in lowered
            for phrase in (
                "worker details",
                "worker log",
                "scan details",
                "show details",
                "show me the details",
            )
        )

    def _asks_for_watch(self, lowered: str) -> bool:
        return "watch" in lowered and any(
            phrase in lowered
            for phrase in ("repo", "repository", "this", "start", "enable")
        )

    def _asks_for_status(self, lowered: str) -> bool:
        return any(
            phrase in lowered
            for phrase in (
                "what are you working on",
                "where are we",
                "status",
                "what's next",
                "what is next",
            )
        )

    def _asks_for_patch_draft(self, lowered: str) -> bool:
        if "draft" in lowered and "fix" in lowered:
            return True
        return lowered.startswith("fix ") or "patch draft" in lowered

    def _is_correction(self, lowered: str) -> bool:
        return any(
            phrase in lowered
            for phrase in (
                "that's expected",
                "that is expected",
                "expected here",
                "ignore this pattern",
                "ignore that pattern",
                "auth is handled upstream",
                "handled upstream",
            )
        )

    def _asks_for_recon(self, lowered: str) -> bool:
        return any(
            phrase in lowered
            for phrase in (
                "scan",
                "audit",
                "review this repo",
                "review the repo",
                "before launch",
                "blocks launch",
                "block release",
                "release blocker",
            )
        )

    def _has_repeated_timeouts(
        self,
        warnings: list[str],
        events: list[str],
    ) -> bool:
        timeout_count = sum("timed out" in warning for warning in warnings)
        disabled_for_timeout = any(
            "disabled" in event and "timeouts" in event
            for event in events
        )
        return timeout_count >= 2 or disabled_for_timeout


def _save_history(
    store: MemoryStore,
    run_id: str,
    findings: list[Finding],
    *,
    mock: bool = False,
) -> None:
    timestamp = datetime.now(UTC)
    record: dict[str, Any] = {
        "run_id": run_id,
        "timestamp": timestamp.isoformat(),
        "mock": mock,
        "finding_count": len(findings),
        "severities": {
            severity.value: sum(
                1 for finding in findings if finding.severity == severity
            )
            for severity in Severity
        },
    }
    path = store.history_dir / f"{timestamp.strftime('%Y%m%d-%H%M%S')}-{run_id}.json"
    path.write_text(json.dumps(record, indent=2))

    findings_path = store.history_dir / f"{run_id}-findings.json"
    payload = [finding.model_dump(mode="json") for finding in findings]
    findings_path.write_text(json.dumps(payload, indent=2))


def _decision_record(
    *,
    summary: str,
    mission_id: str = "",
    level: DecisionLevel = DecisionLevel.INFO,
    rationale: str = "",
    trusted: bool = True,
    next_step: str = "",
) -> DecisionRecord:
    timestamp = datetime.now(UTC).isoformat()
    decision_id = hashlib.sha256(
        f"{timestamp}:{mission_id}:{summary}".encode()
    ).hexdigest()[:12]
    return DecisionRecord(
        id=decision_id,
        timestamp=timestamp,
        mission_id=mission_id,
        level=level,
        summary=summary,
        rationale=rationale,
        trusted=trusted,
        next_step=next_step,
    )
