from pathlib import Path
from types import SimpleNamespace

import pytest

from descry.commands.fix import ApplyPatchResult, PatchSuggestion, PatchTarget
from descry.memory.coworker import DecisionLevel, DecisionRecord, FixQueueItem
from descry.models import Evidence, Finding, FindingSource, Severity, WorkerType
from descry.tui.app import (
    PatchDraftStatus,
    Sidebar,
    SwainAgent,
    command_suggestions_for,
)
from descry.tui.voice import AgentVoice


def _agent() -> SwainAgent:
    app = SimpleNamespace(voice=AgentVoice(), repo_path=Path.cwd() / "repo")
    return SwainAgent(app)  # type: ignore[arg-type]


def _finding() -> Finding:
    return Finding(
        rule="sast.payments",
        severity=Severity.HIGH,
        confidence=0.9,
        title="Client controls subscription state",
        evidence=Evidence(file="backend/app/api/billing.py", anchor="POST /billing"),
        source=FindingSource(
            worker=WorkerType.CLAUDE,
            playbook="sast.payments",
            playbook_version=1,
        ),
    )


def test_local_priority_question_works_without_llm() -> None:
    agent = _agent()
    finding = _finding()
    agent._last_findings = [finding]

    answer = agent._try_local_answer("what should I fix first?")

    assert finding.id[:8] in answer
    assert "draft patch files automatically" in answer


def test_local_launch_question_sets_market_ready_bar() -> None:
    answer = _agent()._try_local_answer("are we ready to ship?")

    assert "auth" in answer
    assert "payments" in answer
    assert "uploads" in answer


def test_sidebar_tracks_scan_subagent_progress() -> None:
    sidebar = Sidebar()

    sidebar.record_scan_event(
        "sast.payments: codex reviewing 8 files"
    )
    sidebar.record_scan_event(
        "sast.payments: codex returned 1 finding"
    )

    assert sidebar.scan_phase == "codex subagent active"
    assert "sast.payments: codex done" in sidebar.subagents


def test_scan_progress_hides_waiting_events_and_summarizes_tasks() -> None:
    agent = _agent()

    assert (
        agent._visible_scan_line("sast.payments: waiting for codex subagent")
        is None
    )
    line = agent._visible_scan_line("sast.payments: codex reviewing 8 files")

    assert line is not None
    assert "Payments" in line
    assert "reviewing 8 files" in line


def test_scan_detail_focus_parses_short_command() -> None:
    agent = _agent()

    assert agent._scan_detail_focus("/scan details auth") == "auth"
    assert agent._scan_detail_focus("/details payments") == "payments"


def test_slash_command_suggestions_show_available_commands() -> None:
    suggestions = command_suggestions_for("/")

    assert "/scan" in suggestions
    assert "/scan details" in suggestions
    assert "/status" in suggestions
    assert "/fix <id>" in suggestions
    assert "/launch-card" in suggestions
    assert "/watch" in suggestions


def test_slash_command_suggestions_filter_by_prefix() -> None:
    suggestions = command_suggestions_for("/sta")

    assert "/status" in suggestions
    assert "/scan" not in suggestions


def test_scan_overview_is_compact_and_points_to_auto_drafting() -> None:
    agent = _agent()
    finding = _finding()
    result = SimpleNamespace(
        findings=[finding],
        secret_hits=[],
        warnings=["secrets.scan codex timed out"],
        decisions=[
            DecisionRecord(
                id="decision1",
                timestamp="2026-05-29T00:00:00+00:00",
                level=DecisionLevel.WARNING,
                summary="Worker result needs attention",
                next_step="Run swain doctor --probe-workers.",
            )
        ],
    )

    overview = agent._scan_overview(result)

    assert overview.startswith("Scan complete.")
    assert "worker warning" in overview
    assert "Fix queue" in overview
    assert f"`{finding.id[:8]}`" in overview
    assert "/scan details" in overview


def test_final_verdict_ready_after_clean_verification() -> None:
    agent = _agent()
    result = SimpleNamespace(
        findings=[],
        secret_hits=[],
        warnings=[],
    )
    status = PatchDraftStatus(
        finding_id="fadc886b12345678",
        title="Missing authorization check",
        ok=True,
        message="Patch applied.",
        applied=True,
    )

    verdict = agent._final_verdict(result, [status])

    assert "VERDICT: READY" in verdict
    assert "Fixed: 1" in verdict
    assert "Still open: 0" in verdict
    assert "git apply --check" in verdict
    assert "I did not commit anything" in verdict


def test_final_verdict_blocks_on_high_remaining_finding() -> None:
    agent = _agent()
    finding = _finding()
    result = SimpleNamespace(
        findings=[finding],
        secret_hits=[],
        warnings=[],
    )

    verdict = agent._final_verdict(result, [])

    assert "VERDICT: BLOCKED" in verdict
    assert "Still open: 1" in verdict


def test_final_verdict_needs_review_when_latest_fix_is_unverified() -> None:
    agent = _agent()
    result = SimpleNamespace(
        findings=[],
        secret_hits=[],
        warnings=[],
    )
    status = PatchDraftStatus(
        finding_id="fadc886b12345678",
        title="Missing authorization check",
        ok=True,
        message="Patch applied.",
        applied=True,
    )

    verdict = agent._final_verdict(result, [status], verification_pending=True)

    assert "VERDICT: NEEDS REVIEW" in verdict
    assert "run /scan again to verify" in verdict


def test_fix_summary_groups_unpatchable_findings() -> None:
    agent = _agent()
    statuses = [
        PatchDraftStatus(
            finding_id="aaaa1111",
            title="Missing file",
            ok=False,
            message="the scan finding didn't name a real source file",
        ),
        PatchDraftStatus(
            finding_id="bbbb2222",
            title="Missing file",
            ok=False,
            message="the scan finding didn't name a real source file",
        ),
    ]

    summary = agent._fix_draft_summary(statuses, total=2)

    assert "Skipped 2 findings" in summary
    assert "- 2 need fresh scan evidence" in summary
    assert "aaaa1111" not in summary


@pytest.mark.asyncio
async def test_scan_auto_drafts_fix_queue_to_patch_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _FakeApp(tmp_path)
    agent = SwainAgent(app)  # type: ignore[arg-type]
    finding = _finding()
    source = tmp_path / finding.evidence.file
    source.parent.mkdir(parents=True)
    source.write_text("print('hello')\n")
    item = FixQueueItem(
        id=finding.id[:8],
        finding_id=finding.id,
        title=finding.title,
        severity=finding.severity.value,
        confidence=finding.confidence,
        exposure="network-exposed",
        file=finding.evidence.file,
        line=finding.evidence.line_start,
        score=90,
        rationale="high confidence",
    )

    async def fake_generate(*args, **kwargs) -> PatchSuggestion:
        return PatchSuggestion(
            ok=True,
            message="Patch draft ready.",
            diff="diff --git a/app.py b/app.py\n",
        )

    def fake_resolve(*args, **kwargs) -> PatchTarget:
        return PatchTarget(
            ok=True,
            message="Ready to ask Codex.",
            finding=finding.model_dump(mode="json"),
            files=(source,),
            evidence_file=finding.evidence.file,
        )

    def fake_apply(*args, **kwargs) -> ApplyPatchResult:
        return ApplyPatchResult(applied=True, message="Patch applied.")

    monkeypatch.setattr(
        "descry.commands.fix.generate_patch_suggestion",
        fake_generate,
    )
    monkeypatch.setattr("descry.commands.fix.resolve_patch_target", fake_resolve)
    monkeypatch.setattr("descry.commands.fix.apply_patch_draft", fake_apply)

    await agent._draft_fix_queue([item])

    patch_path = tmp_path / ".swain" / "fixes" / f"{finding.id[:8]}.patch"
    assert patch_path.exists()
    assert "diff --git" in patch_path.read_text()
    assert any("asking codex 1/1" in event for event in app.events)
    assert any("applied" in line for line in app.log.lines)


@pytest.mark.asyncio
async def test_scan_auto_fix_skips_previous_clean_apply_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _FakeApp(tmp_path)
    agent = SwainAgent(app)  # type: ignore[arg-type]
    finding = _finding()
    source = tmp_path / finding.evidence.file
    source.parent.mkdir(parents=True)
    source.write_text("print('hello')\n")
    item = FixQueueItem(
        id=finding.id[:8],
        finding_id=finding.id,
        title=finding.title,
        severity=finding.severity.value,
        confidence=finding.confidence,
        exposure="network-exposed",
        file=finding.evidence.file,
        line=finding.evidence.line_start,
        score=90,
        rationale="high confidence",
    )
    generate_calls = 0

    async def fake_generate(*args, **kwargs) -> PatchSuggestion:
        nonlocal generate_calls
        generate_calls += 1
        return PatchSuggestion(
            ok=True,
            message="Patch draft ready.",
            diff="diff --git a/app.py b/app.py\n",
        )

    def fake_resolve(*args, **kwargs) -> PatchTarget:
        return PatchTarget(
            ok=True,
            message="Ready to ask Codex.",
            finding=finding.model_dump(mode="json"),
            files=(source,),
            evidence_file=finding.evidence.file,
        )

    def fake_apply(*args, **kwargs) -> ApplyPatchResult:
        return ApplyPatchResult(
            applied=False,
            message="Patch did not apply cleanly.",
            exit_code=1,
        )

    monkeypatch.setattr(
        "descry.commands.fix.generate_patch_suggestion",
        fake_generate,
    )
    monkeypatch.setattr("descry.commands.fix.resolve_patch_target", fake_resolve)
    monkeypatch.setattr("descry.commands.fix.apply_patch_draft", fake_apply)

    first = await agent._draft_fix_queue([item])
    second = await agent._draft_fix_queue([item])

    assert generate_calls == 1
    assert first[0].message == "Patch did not apply cleanly."
    assert "already tried on unchanged files" in second[0].message


class _FakeLog:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def agent_label(self) -> None:
        self.lines.append("Swain")

    def write(self, text: str) -> None:
        self.lines.append(text)

    def scan_event(self, text: str) -> None:
        self.lines.append(text)


class _FakeApp:
    def __init__(self, repo_path: Path) -> None:
        self.voice = AgentVoice()
        self.repo_path = repo_path
        self.log = _FakeLog()
        self.events: list[str] = []

    def query_one(self, *args, **kwargs) -> _FakeLog:
        return self.log

    def record_scan_event(self, text: str) -> None:
        self.events.append(text)
