"""
Executor — runs a Mission's tasks through the worker pool.
Handles retry (once, with reduced scope), dedup, and finding synthesis.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime
from pathlib import Path
from typing import Callable

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from descry.models import Finding, Mission, Task, WorkerReport, WorkerType
from descry.orchestrator.pool import WorkerPool
from descry.playbooks.loader import PlaybookLoader
from descry.playbooks.renderer import render_prompt
from descry.memory.profile import ProjectProfile
from descry.memory.conventions import ConventionStore
from descry.memory.calibration import CalibrationStore
from descry.workers.base import WorkerResult

console = Console()


class Executor:
    def __init__(
        self,
        pool: WorkerPool,
        loader: PlaybookLoader,
        profile: ProjectProfile,
        conventions: ConventionStore,
        calibration: CalibrationStore,
        repo_root: Path,
    ) -> None:
        self.pool = pool
        self.loader = loader
        self.profile = profile
        self.conventions = conventions
        self.calibration = calibration
        self.repo_root = repo_root

    async def execute(
        self,
        mission: Mission,
        on_finding: Callable[[Finding], None] | None = None,
    ) -> list[Finding]:
        all_findings: list[Finding] = []
        run_id = uuid.uuid4().hex[:8]

        playbooks_by_id = {pb["id"]: pb for pb in self.loader.load_all()}

        with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console) as progress:
            for task in mission.tasks:
                pb = playbooks_by_id.get(task.playbook_id)
                if not pb:
                    continue

                prog_task = progress.add_task(f"[cyan]{task.playbook_id}", total=None)

                prompt = self._build_prompt(pb, task)
                files = [self.repo_root / f for f in task.files]

                result = await self.pool.run_task(task, prompt, files, self.repo_root)

                # Retry once with half the files if failed
                if result.report is None and not result.timed_out:
                    task.files = task.files[: len(task.files) // 2]
                    files = [self.repo_root / f for f in task.files]
                    result = await self.pool.run_task(task, prompt, files, self.repo_root)

                if result.report:
                    findings = self._process_report(result.report, run_id)
                    all_findings.extend(findings)
                    for f in findings:
                        if on_finding:
                            on_finding(f)
                elif result.timed_out:
                    console.print(f"[yellow]  ⚠ {task.playbook_id} timed out")
                elif result.parse_error:
                    console.print(f"[yellow]  ⚠ {task.playbook_id} parse error: {result.parse_error[:80]}")

                progress.remove_task(prog_task)

        return self._deduplicate(all_findings)

    def _build_prompt(self, playbook: dict, task: Task) -> str:
        context_block = self.profile.to_context_block()
        convention_lines = self.conventions.to_context_lines()
        min_conf = self.calibration.min_confidence()

        context_block += f"\nCALIBRATION: Only report findings with confidence >= {min_conf:.1f}"
        if convention_lines:
            context_block += "\nACCEPTED PATTERNS (do not report these as findings):\n" + "\n".join(convention_lines)

        return render_prompt(
            playbook=playbook,
            learned_context=context_block,
            accepted_patterns=convention_lines,
            file_list=task.files,
        )

    def _process_report(self, report: WorkerReport, run_id: str) -> list[Finding]:
        findings = []
        for f in report.findings:
            f.source.run_id = run_id
            f.lifecycle.last_seen = datetime.utcnow()
            findings.append(f)
        return findings

    def _deduplicate(self, findings: list[Finding]) -> list[Finding]:
        """Collapse same finding from multiple workers into one (highest confidence wins)."""
        seen: dict[str, Finding] = {}
        for f in findings:
            if f.id not in seen or f.confidence > seen[f.id].confidence:
                seen[f.id] = f
        return list(seen.values())
