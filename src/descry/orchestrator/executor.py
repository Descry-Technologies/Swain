"""
Executor — runs a Mission's tasks through the worker pool.
Handles retry (once, with reduced scope), dedup, and finding synthesis.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from descry.memory.calibration import CalibrationStore
from descry.memory.conventions import ConventionStore
from descry.memory.profile import ProjectProfile
from descry.models import Finding, Mission, Task, WorkerReport
from descry.orchestrator.pool import WorkerPool
from descry.playbooks.loader import PlaybookLoader
from descry.playbooks.renderer import render_prompt
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
        self.task_warnings: list[str] = []

    async def execute(
        self,
        mission: Mission,
        on_finding: Callable[[Finding], None] | None = None,
    ) -> list[Finding]:
        all_findings: list[Finding] = []
        self.task_warnings = []
        run_id = uuid.uuid4().hex[:8]

        playbooks_by_id = {pb["id"]: pb for pb in self.loader.load_all()}

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            async def run_one(task: Task) -> list[Finding]:
                pb = playbooks_by_id.get(task.playbook_id)
                if not pb:
                    return []

                prog_task = progress.add_task(f"[cyan]{task.playbook_id}", total=None)
                try:
                    result = await self._run_task(task, pb)
                    if result.report:
                        return self._process_report(result.report, run_id)
                    if result.timed_out:
                        self._record_warning(f"{task.playbook_id} timed out")
                    elif result.parse_error:
                        self._record_warning(
                            f"{task.playbook_id} parse error: "
                            f"{result.parse_error[:120]}",
                        )
                    return []
                finally:
                    progress.remove_task(prog_task)

            task_results = await asyncio.gather(
                *(run_one(task) for task in mission.tasks)
            )

        for findings in task_results:
            all_findings.extend(findings)
            for finding in findings:
                if on_finding:
                    on_finding(finding)

        return self._deduplicate(all_findings)

    async def _run_task(self, task: Task, playbook: dict) -> WorkerResult:
        prompt = self._build_prompt(playbook, task)
        files = [self.repo_root / f for f in task.files]
        result = await self.pool.run_task(task, prompt, files, self.repo_root)

        # Retry once with half the files if failed.
        if result.report is None and len(task.files) > 1:
            retry_task = task.model_copy(
                update={"files": task.files[: max(1, len(task.files) // 2)]},
            )
            retry_prompt = self._build_prompt(playbook, retry_task)
            retry_files = [self.repo_root / f for f in retry_task.files]
            result = await self.pool.run_task(
                retry_task,
                retry_prompt,
                retry_files,
                self.repo_root,
            )
        return result

    def _record_warning(self, warning: str) -> None:
        self.task_warnings.append(warning)
        console.print(f"[yellow]  ⚠ {warning}")

    def _build_prompt(self, playbook: dict, task: Task) -> str:
        context_block = self.profile.to_context_block()
        convention_lines = self.conventions.to_context_lines()
        min_conf = self.calibration.min_confidence()

        context_block += (
            "\nCALIBRATION: Only report findings with confidence "
            f">= {min_conf:.1f}"
        )
        if convention_lines:
            context_block += (
                "\nACCEPTED PATTERNS (do not report these as findings):\n"
                + "\n".join(convention_lines)
            )

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
            f.lifecycle.last_seen = datetime.now(UTC)
            findings.append(f)
        return findings

    def _deduplicate(self, findings: list[Finding]) -> list[Finding]:
        """Collapse same finding from multiple workers into one."""
        seen: dict[str, Finding] = {}
        for f in findings:
            if f.id not in seen or f.confidence > seen[f.id].confidence:
                seen[f.id] = f
        return list(seen.values())
