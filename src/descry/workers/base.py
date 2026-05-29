"""Abstract worker base — all CLI adapters implement this interface."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from descry.models import WorkerReport, WorkerType


@dataclass
class WorkerResult:
    report: WorkerReport | None
    stderr: str = ""
    exit_code: int = 0
    timed_out: bool = False
    parse_error: str = ""


class BaseWorker(ABC):
    """
    All workers share the same contract:
    - receive a task prompt + list of files in an isolated worktree
    - return a WorkerReport with structured findings
    - never write to the original repo
    """

    MAX_OUTPUT_BYTES = 2 * 1024 * 1024  # 2 MB stdout cap
    HEARTBEAT_TIMEOUT_S = 30  # kill if no stdout for 30s

    def __init__(self, timeout_s: int = 180) -> None:
        self.timeout_s = timeout_s

    @property
    @abstractmethod
    def worker_type(self) -> WorkerType: ...

    @abstractmethod
    def is_available(self) -> bool:
        """Check if the CLI binary is installed and authenticated."""
        ...

    @abstractmethod
    async def _build_command(self, prompt: str, worktree: Path) -> list[str]: ...

    async def run(
        self,
        task_id: str,
        prompt: str,
        files: list[Path],
        repo_root: Path,
        *,
        playbook_id: str = "",
        playbook_version: int = 1,
        timeout_s: int | None = None,
    ) -> WorkerResult:
        """
        Runs the worker in an isolated temporary worktree.
        Selected files are copied so worker writes cannot affect the original repo.
        """
        with tempfile.TemporaryDirectory(prefix=f"swain-{task_id}-") as tmpdir:
            worktree = Path(tmpdir) / "repo"
            worktree.mkdir()
            self._copy_files(files, repo_root, worktree)
            return await self._execute(
                task_id,
                prompt,
                worktree,
                playbook_id,
                playbook_version,
                timeout_s,
            )

    def _copy_files(self, files: list[Path], repo_root: Path, worktree: Path) -> None:
        for source in files:
            if not source.is_file():
                continue
            rel = source.relative_to(repo_root)
            dest = worktree / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            if not dest.exists():
                shutil.copy2(source, dest)

    async def _execute(
        self,
        task_id: str,
        prompt: str,
        worktree: Path,
        playbook_id: str,
        playbook_version: int,
        timeout_s: int | None = None,
    ) -> WorkerResult:
        cmd = await self._build_command(prompt, worktree)
        env = self._sanitized_env()
        effective_timeout_s = timeout_s or self.timeout_s

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=worktree,
                env=env,
            )
        except FileNotFoundError as e:
            return WorkerResult(report=None, stderr=str(e), exit_code=127)

        try:
            stdout_raw, stderr_raw = await asyncio.wait_for(
                proc.communicate(),
                timeout=effective_timeout_s,
            )
        except TimeoutError:
            proc.kill()
            await proc.wait()
            return WorkerResult(report=None, timed_out=True, exit_code=-1)

        if len(stdout_raw) > self.MAX_OUTPUT_BYTES:
            return WorkerResult(
                report=None,
                stderr="stdout exceeded 2MB cap",
                exit_code=-2,
            )

        stdout = stdout_raw.decode("utf-8", errors="replace")
        stderr = stderr_raw.decode("utf-8", errors="replace")
        exit_code = proc.returncode or 0

        return self._parse_output(
            task_id,
            stdout,
            stderr,
            exit_code,
            playbook_id,
            playbook_version,
        )

    def _parse_output(
        self,
        task_id: str,
        stdout: str,
        stderr: str,
        exit_code: int,
        playbook_id: str = "",
        playbook_version: int = 1,
    ) -> WorkerResult:
        raw = self._extract_json(stdout)
        if raw is None:
            diagnostic = self._diagnostic_snippet(stdout, stderr)
            parse_error = f"No valid JSON found in output (exit={exit_code})"
            if diagnostic:
                parse_error = f"{parse_error}: {diagnostic}"
            return WorkerResult(
                report=None,
                stderr=stderr,
                exit_code=exit_code,
                parse_error=parse_error,
            )
        try:
            report_data = self._normalize_report(
                raw,
                task_id,
                playbook_id,
                playbook_version,
            )
            report = WorkerReport.model_validate(report_data)
            return WorkerResult(report=report, stderr=stderr, exit_code=exit_code)
        except Exception as e:
            diagnostic = self._diagnostic_snippet(json.dumps(raw), stderr)
            parse_error = f"Invalid worker report schema: {e}"
            if diagnostic:
                parse_error = f"{parse_error}: {diagnostic}"
            return WorkerResult(
                report=None,
                stderr=stderr,
                exit_code=exit_code,
                parse_error=parse_error,
            )

    def _extract_json(self, text: str) -> dict | None:
        """Extract a complete worker report JSON object from noisy CLI output."""
        text = text.strip()
        if not text:
            return None

        try:
            raw = json.loads(text)
            if isinstance(raw, dict):
                return raw
            if isinstance(raw, list):
                return {"findings": raw}
        except json.JSONDecodeError:
            ...

        candidates = list(self._json_object_candidates(text))
        report_candidates = [
            candidate for candidate in candidates if self._is_report_like(candidate)
        ]
        if report_candidates:
            return max(report_candidates, key=self._report_candidate_score)
        if candidates:
            return candidates[-1]
        return None

    def _json_object_candidates(self, text: str) -> list[dict]:
        decoder = json.JSONDecoder()
        candidates: list[dict] = []
        for index, char in enumerate(text):
            if char not in "{[":
                continue
            if char == "[" and self._previous_nonspace(text, index) == ":":
                continue
            try:
                raw, _ = decoder.raw_decode(text[index:])
            except json.JSONDecodeError:
                continue
            if isinstance(raw, dict):
                candidates.append(raw)
            elif isinstance(raw, list):
                candidates.append({"findings": raw})
        return candidates

    def _is_report_like(self, raw: dict) -> bool:
        return any(
            isinstance(raw.get(key), list)
            for key in ("findings", "issues", "vulnerabilities", "results")
        ) or {
            "rule",
            "severity",
            "evidence",
        }.issubset(raw)

    def _report_candidate_score(self, raw: dict) -> int:
        score = 0
        if isinstance(raw.get("findings"), list):
            score += 5
        if raw.get("playbook"):
            score += 3
        if raw.get("worker"):
            score += 2
        if raw.get("task_id"):
            score += 1
        if {"rule", "severity", "evidence"}.issubset(raw):
            score += 1
        return score

    def _previous_nonspace(self, text: str, index: int) -> str:
        for char in reversed(text[:index]):
            if not char.isspace():
                return char
        return ""

    def _normalize_report(
        self,
        raw: dict,
        task_id: str,
        playbook_id: str,
        playbook_version: int,
    ) -> dict:
        if "findings" not in raw and {"rule", "severity", "evidence"}.issubset(raw):
            raw = {"schema_version": "1.0", "findings": [raw]}

        if "findings" not in raw:
            for alternate_key in ("issues", "vulnerabilities", "results"):
                if isinstance(raw.get(alternate_key), list):
                    raw["findings"] = raw[alternate_key]
                    break

        report_playbook = raw.get("playbook") or playbook_id
        report_version = raw.get("playbook_version") or playbook_version
        findings = raw.get("findings", [])
        if isinstance(findings, list):
            findings = [
                self._normalize_finding(
                    finding,
                    report_playbook,
                    report_version,
                )
                for finding in findings
                if isinstance(finding, dict)
            ]

        return {
            **raw,
            "schema_version": raw.get("schema_version", "1.0"),
            "task_id": task_id,
            "worker": self.worker_type,
            "playbook": report_playbook,
            "playbook_version": report_version,
            "findings": findings if isinstance(findings, list) else [],
        }

    def _normalize_finding(
        self,
        finding: dict,
        report_playbook: str,
        report_version: int,
    ) -> dict:
        finding = dict(finding)
        # Worker-provided IDs are often local counters like F001 or verbose rule
        # labels. Swain owns stable IDs so /fix and /feedback stay usable.
        finding.pop("id", None)
        finding.setdefault("schema_version", "1.0")
        finding["rule"] = finding.get("rule") or report_playbook or "unknown"
        finding["severity"] = self._normalize_severity(finding.get("severity"))
        finding["confidence"] = self._normalize_confidence(
            finding.get("confidence"),
        )
        finding["title"] = self._normalize_title(finding, report_playbook)
        finding["description"] = self._normalize_description(finding)
        finding["evidence"] = self._normalize_evidence(finding)
        finding["remediation"] = self._normalize_remediation(
            finding.get("remediation") or finding.get("fix")
        )
        finding["exploitability"] = self._normalize_exploitability(
            finding.get("exploitability")
        )
        finding["cwe"] = self._normalize_optional_string(finding.get("cwe"))
        finding["owasp"] = self._normalize_optional_string(finding.get("owasp"))

        source = finding.get("source")
        if not isinstance(source, dict):
            source = {}
        source.setdefault("worker", self.worker_type.value)
        source.setdefault("playbook", report_playbook)
        source.setdefault("playbook_version", report_version)
        finding["source"] = source
        return finding

    def _normalize_severity(self, value: object) -> str:
        severity = str(value or "medium").strip().lower()
        if severity in {"critical", "high", "medium", "low", "info"}:
            return severity
        if severity in {"warning", "warn", "moderate"}:
            return "medium"
        return "medium"

    def _normalize_confidence(self, value: object) -> float:
        if value is None:
            return 0.5
        if isinstance(value, int | float):
            return min(max(float(value), 0.0), 1.0)
        text = str(value).strip().lower()
        if text.endswith("%"):
            try:
                return min(max(float(text[:-1]) / 100, 0.0), 1.0)
            except ValueError:
                return 0.5
        labels = {"low": 0.35, "medium": 0.6, "high": 0.85}
        if text in labels:
            return labels[text]
        try:
            parsed = float(text)
        except ValueError:
            return 0.5
        if parsed > 1:
            parsed = parsed / 100
        return min(max(parsed, 0.0), 1.0)

    def _normalize_title(self, finding: dict, report_playbook: str) -> str:
        for key in ("title", "issue", "summary", "message", "name"):
            value = self._normalize_optional_string(finding.get(key))
            if value:
                return value[:180]
        description = self._normalize_optional_string(finding.get("description"))
        if description:
            return description[:180]
        return f"Potential {report_playbook or 'security'} finding"

    def _normalize_description(self, finding: dict) -> str:
        parts = []
        for key in ("description", "details", "impact", "exploit_scenario"):
            value = self._normalize_optional_string(finding.get(key))
            if value:
                parts.append(value)
        return "\n\n".join(parts)

    def _normalize_evidence(self, finding: dict) -> dict:
        evidence = finding.get("evidence")
        if not isinstance(evidence, dict):
            evidence = {}
        else:
            evidence = dict(evidence)

        evidence["file"] = (
            evidence.get("file")
            or evidence.get("path")
            or finding.get("file")
            or finding.get("path")
            or "unknown"
        )
        line = (
            evidence.get("line_start")
            or evidence.get("line")
            or finding.get("line_start")
            or finding.get("line")
        )
        evidence["line_start"] = self._normalize_line(line)
        if evidence.get("line_end") is not None:
            evidence["line_end"] = self._normalize_line(evidence.get("line_end"))
        evidence["anchor"] = (
            evidence.get("anchor")
            or finding.get("anchor")
            or finding.get("function")
            or finding.get("symbol")
            or finding.get("title")
            or evidence["file"]
        )
        return evidence

    def _normalize_line(self, value: object) -> int | None:
        if value is None:
            return None
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return None
        return parsed if parsed > 0 else None

    def _normalize_remediation(self, value: object) -> dict:
        if isinstance(value, dict):
            return value
        text = self._normalize_optional_string(value)
        return {"summary": text or ""}

    def _normalize_exploitability(self, value: object) -> dict:
        if isinstance(value, dict):
            return value
        text = self._normalize_optional_string(value)
        return {"assessment": text or ""}

    def _normalize_optional_string(self, value: object) -> str | None:
        if value is None:
            return None
        if isinstance(value, list | tuple | set):
            values = [str(item).strip() for item in value if str(item).strip()]
            return ", ".join(values) if values else None
        text = str(value).strip()
        return text or None

    def _diagnostic_snippet(self, stdout: str, stderr: str) -> str:
        for stream in (stderr, stdout):
            for line in stream.splitlines():
                stripped = line.strip()
                if stripped:
                    return stripped[:200]
        return ""

    def _sanitized_env(self) -> dict[str, str]:
        """Pass only necessary env vars to workers — reduce injection surface."""
        allowed = {
            "ANTHROPIC_API_KEY", "OPENAI_API_KEY",
            "HOME", "PATH", "LANG", "LC_ALL", "TERM",
            "CLAUDE_CONFIG_DIR", "CODEX_HOME",
        }
        return {k: v for k, v in os.environ.items() if k in allowed}
