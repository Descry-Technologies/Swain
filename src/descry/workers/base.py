"""Abstract worker base — all CLI adapters implement this interface."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

from descry.models import Finding, WorkerReport, WorkerType


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

    async def run(self, task_id: str, prompt: str, files: list[Path], repo_root: Path) -> WorkerResult:
        """
        Runs the worker in an isolated read-only worktree.
        Files are symlinked from the original repo — no copies, no writes.
        """
        with tempfile.TemporaryDirectory(prefix=f"descry-{task_id}-") as tmpdir:
            worktree = Path(tmpdir) / "repo"
            worktree.mkdir()
            self._link_files(files, repo_root, worktree)
            return await self._execute(task_id, prompt, worktree)

    def _link_files(self, files: list[Path], repo_root: Path, worktree: Path) -> None:
        for f in files:
            rel = f.relative_to(repo_root)
            dest = worktree / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            if not dest.exists():
                dest.symlink_to(f)

    async def _execute(self, task_id: str, prompt: str, worktree: Path) -> WorkerResult:
        cmd = await self._build_command(prompt, worktree)
        env = self._sanitized_env()

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

        stdout_chunks: list[bytes] = []
        total_bytes = 0
        killed = False

        async def read_stdout() -> None:
            nonlocal total_bytes, killed
            assert proc.stdout
            while True:
                chunk = await proc.stdout.read(4096)
                if not chunk:
                    break
                total_bytes += len(chunk)
                if total_bytes > self.MAX_OUTPUT_BYTES:
                    proc.kill()
                    killed = True
                    break
                stdout_chunks.append(chunk)

        try:
            stdout_raw, stderr_raw = await asyncio.wait_for(
                asyncio.gather(read_stdout(), proc.communicate()),
                timeout=self.timeout_s,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return WorkerResult(report=None, timed_out=True, exit_code=-1)

        stdout = b"".join(stdout_chunks).decode("utf-8", errors="replace")
        stderr = stderr_raw[1].decode("utf-8", errors="replace") if isinstance(stderr_raw, tuple) else ""
        exit_code = proc.returncode or 0

        if killed:
            return WorkerResult(report=None, stderr="stdout exceeded 2MB cap", exit_code=-2)

        return self._parse_output(task_id, stdout, stderr, exit_code)

    def _parse_output(self, task_id: str, stdout: str, stderr: str, exit_code: int) -> WorkerResult:
        raw = self._extract_json(stdout)
        if raw is None:
            return WorkerResult(
                report=None,
                stderr=stderr,
                exit_code=exit_code,
                parse_error=f"No valid JSON found in output (exit={exit_code})",
            )
        try:
            report = WorkerReport.model_validate({**raw, "task_id": task_id, "worker": self.worker_type})
            return WorkerResult(report=report, stderr=stderr, exit_code=exit_code)
        except Exception as e:
            return WorkerResult(report=None, stderr=stderr, exit_code=exit_code, parse_error=str(e))

    def _extract_json(self, text: str) -> dict | None:
        """Extract the first complete JSON object from potentially noisy output."""
        text = text.strip()
        # Direct parse
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        # Find JSON block in markdown fences or mixed output
        for start_char in ["{", "["]:
            idx = text.find(start_char)
            if idx == -1:
                continue
            for end_char in ["}", "]"]:
                ridx = text.rfind(end_char)
                if ridx == -1:
                    continue
                try:
                    return json.loads(text[idx : ridx + 1])
                except json.JSONDecodeError:
                    continue
        return None

    def _sanitized_env(self) -> dict[str, str]:
        """Pass only necessary env vars to workers — reduce injection surface."""
        allowed = {
            "ANTHROPIC_API_KEY", "OPENAI_API_KEY",
            "HOME", "PATH", "LANG", "LC_ALL", "TERM",
            "CLAUDE_CONFIG_DIR", "CODEX_HOME",
        }
        return {k: v for k, v in os.environ.items() if k in allowed}
