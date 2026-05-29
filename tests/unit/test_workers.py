from pathlib import Path

import pytest

from descry.models import Task, WorkerType
from descry.orchestrator.pool import WorkerPool
from descry.workers.api_worker import (
    OpenAIResponsesAPIWorker,
    _openai_text,
)
from descry.workers.base import BaseWorker, WorkerResult
from descry.workers.claude_worker import ClaudeWorker
from descry.workers.codex_worker import CodexWorker


class DummyWorker(BaseWorker):
    worker_type = WorkerType.CLAUDE

    def is_available(self) -> bool:
        return True

    async def _build_command(self, prompt: str, worktree: Path) -> list[str]:
        return ["echo", "{}"]


def test_extract_json_prefers_report_object_from_noisy_codex_output() -> None:
    worker = DummyWorker()
    output = """
OpenAI Codex v0.135.0
user
Reply with exactly {"ok": true}
codex
{"schema_version":"1.0","worker":"codex","playbook":"sast.xss.react","playbook_version":1,"findings":[],"partial":false}
tokens used
"""

    raw = worker._extract_json(output)

    assert raw is not None
    assert raw["playbook"] == "sast.xss.react"
    assert raw["findings"] == []


def test_parse_output_fills_worker_report_metadata_and_finding_source() -> None:
    worker = DummyWorker()
    output = """
```json
{
  "findings": [
    {
      "rule": "sast.sql-injection",
      "severity": "high",
      "confidence": 0.9,
      "title": "Raw query uses request data",
      "evidence": {
        "file": "backend/app/main.py",
        "line_start": 12,
        "anchor": "def search"
      }
    }
  ],
  "partial": false
}
```
"""

    result = worker._parse_output("task-1", output, "", 0, "sast.sql-injection", 1)

    assert result.report is not None
    assert result.report.playbook == "sast.sql-injection"
    assert result.report.findings[0].source.worker == WorkerType.CLAUDE
    assert result.report.findings[0].source.playbook == "sast.sql-injection"


def test_parse_output_normalizes_common_issue_shape() -> None:
    worker = DummyWorker()
    output = """
{
  "issues": [
    {
      "issue": "Unauthenticated tenant settings endpoint",
      "severity": "HIGH",
      "confidence": "85%",
      "file": "backend/app/api/tenants.py",
      "line": "42",
      "fix": "Require the current user dependency."
    }
  ]
}
"""

    result = worker._parse_output("task-1", output, "", 0, "sast.auth.python", 1)

    assert result.report is not None
    finding = result.report.findings[0]
    assert finding.rule == "sast.auth.python"
    assert finding.severity == "high"
    assert finding.confidence == 0.85
    assert finding.title == "Unauthenticated tenant settings endpoint"
    assert finding.evidence.file == "backend/app/api/tenants.py"
    assert finding.evidence.line_start == 42
    assert finding.remediation.summary == "Require the current user dependency."


def test_parse_output_replaces_worker_supplied_finding_ids() -> None:
    worker = DummyWorker()
    output = """
{
  "findings": [
    {
      "id": "F001",
      "rule": "secrets.scan",
      "severity": "high",
      "confidence": 0.8,
      "title": "Hardcoded secret",
      "evidence": {
        "file": "backend/app/config.py",
        "line_start": 12,
        "anchor": "SECRET_KEY"
      }
    }
  ]
}
"""

    result = worker._parse_output("task-1", output, "", 0, "secrets.scan", 1)

    assert result.report is not None
    assert result.report.findings[0].id != "F001"
    assert len(result.report.findings[0].id) == 16


def test_parse_error_includes_cli_diagnostic() -> None:
    worker = DummyWorker()

    result = worker._parse_output("task-1", "You've hit your session limit", "", 1)

    assert result.report is None
    assert "session limit" in result.parse_error


def test_openai_text_extracts_responses_output() -> None:
    text = _openai_text({
        "output": [
            {
                "content": [
                    {"type": "output_text", "text": '{"findings":[]}'},
                ],
            }
        ],
    })

    assert text == '{"findings":[]}'


def test_api_prompt_includes_bounded_file_bundle(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    source = repo / "app.py"
    source.parent.mkdir()
    source.write_text("print('secret-ish test data')\n")
    worker = OpenAIResponsesAPIWorker(
        model="gpt-test",
        api_key_env="OPENAI_API_KEY",
        api_base_url="https://api.openai.com/v1",
        file_char_limit=10,
    )

    prompt = worker._prompt_with_files("Review", [source], repo)

    assert "--- FILE: app.py ---" in prompt
    assert "print('sec" in prompt
    assert "FILE BUNDLE TRUNCATED" in prompt


@pytest.mark.asyncio
async def test_claude_model_option_is_before_prompt(tmp_path: Path) -> None:
    cmd = await ClaudeWorker(model="sonnet")._build_command("Prompt", tmp_path)

    assert cmd.index("--model") < cmd.index("-p")
    assert cmd[cmd.index("--model") + 1] == "sonnet"


@pytest.mark.asyncio
async def test_codex_model_option_is_before_prompt(tmp_path: Path) -> None:
    cmd = await CodexWorker(model="gpt-test")._build_command("Prompt", tmp_path)

    assert cmd.index("-m") < len(cmd) - 1
    assert cmd[cmd.index("-m") + 1] == "gpt-test"
    assert "Prompt" in cmd[-1]


def test_worker_pool_disables_quota_limited_worker_only() -> None:
    pool = WorkerPool()

    assert pool._should_disable_worker(
        WorkerResult(report=None, parse_error="You've hit your session limit")
    )
    assert not pool._should_disable_worker(
        WorkerResult(
            report=None,
            parse_error="Invalid worker report schema: authentication bypass",
        )
    )


@pytest.mark.asyncio
async def test_worker_pool_emits_worker_progress_events(tmp_path: Path) -> None:
    pool = WorkerPool()
    pool.register(DummyWorker())
    task = Task(
        id="task-1",
        playbook_id="sast.xss.react",
        worker=WorkerType.CLAUDE,
        files=["frontend/src/App.tsx"],
    )
    events: list[str] = []

    await pool.run_task(
        task,
        "Return JSON",
        [],
        tmp_path,
        on_event=events.append,
    )

    assert any("waiting for claude subagent" in event for event in events)
    assert any("claude reviewing 0 files" in event for event in events)
    assert any("claude returned 0 findings" in event for event in events)
