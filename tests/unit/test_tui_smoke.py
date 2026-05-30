from pathlib import Path
from types import SimpleNamespace

import pytest
from textual.widgets import Input, Static

import descry.tui.app as tui
from descry.commands.fix import ApplyPatchResult, PatchSuggestion, PatchTarget
from descry.memory.config import SwainConfig
from descry.memory.coworker import FixQueueItem
from descry.memory.profile import ProjectProfile
from descry.memory.store import MemoryStore
from descry.models import Evidence, Finding, FindingSource, Severity, WorkerType
from descry.tui.app import ChatLog, SwainApp


def _disable_typewriter(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "_CHAR_DELAY",
        "_WORD_DELAY",
        "_COMMA_DELAY",
        "_PERIOD_DELAY",
        "_NEWLINE_DELAY",
    ):
        monkeypatch.setattr(tui, name, 0)


def _chat_text(log: ChatLog) -> str:
    return "\n".join(line.text for line in log.lines)


@pytest.mark.asyncio
async def test_first_run_tui_greets_without_mutating_repo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _disable_typewriter(monkeypatch)
    repo = tmp_path / "demo-repo"
    repo.mkdir()

    app = SwainApp(repo_path=repo)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause(0.2)
        log = app.query_one("#chat-log", ChatLog)
        text = _chat_text(log)

        assert "demo-repo" in text
        assert "first scan" in text or "/scan" in text
        assert not (repo / ".swain").exists()
        assert app._agent is not None
        assert app._agent._profile is None


@pytest.mark.asyncio
async def test_tui_answers_launch_readiness_without_llm(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _disable_typewriter(monkeypatch)
    repo = tmp_path / "demo-repo"
    repo.mkdir()

    app = SwainApp(repo_path=repo)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause(0.2)
        input_box = app.query_one("#message-input", Input)
        input_box.value = "are we ready to ship?"
        await pilot.press("enter")
        await pilot.pause(0.2)

        text = _chat_text(app.query_one("#chat-log", ChatLog))
        assert "auth" in text
        assert "payments" in text
        assert "uploads" in text
        assert "/scan" in text


@pytest.mark.asyncio
async def test_tui_shows_slash_command_suggestions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _disable_typewriter(monkeypatch)
    repo = tmp_path / "demo-repo"
    repo.mkdir()

    app = SwainApp(repo_path=repo)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause(0.2)
        input_box = app.query_one("#message-input", Input)
        input_box.value = "/"
        await pilot.pause(0.1)

        suggestions = app.query_one("#command-suggestions", Static)
        assert suggestions.display is True
        assert "/scan" in suggestions.content
        assert "/status" in suggestions.content


@pytest.mark.asyncio
async def test_tui_scan_identifies_fixes_and_verifies_from_chat(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _disable_typewriter(monkeypatch)
    repo = tmp_path / "demo-repo"
    source = repo / "backend" / "app" / "api" / "billing.py"
    source.parent.mkdir(parents=True)
    source.write_text("allow = request.json['active']\n")
    store = MemoryStore(repo)
    ProjectProfile(
        repo_name=repo.name,
        languages=["python"],
        frameworks=["fastapi"],
        deps=["fastapi"],
        has_payments=True,
    ).save(store)
    SwainConfig.completed(worker_mode="claude").save(store)

    finding = Finding(
        rule="sast.payments",
        severity=Severity.HIGH,
        confidence=0.92,
        title="Client controls subscription state",
        evidence=Evidence(
            file="backend/app/api/billing.py",
            line_start=1,
            anchor="request.json['active']",
        ),
        source=FindingSource(
            worker=WorkerType.CLAUDE,
            playbook="sast.payments",
            playbook_version=1,
        ),
    )
    queue_item = FixQueueItem(
        id=finding.id[:8],
        finding_id=finding.id,
        title=finding.title,
        severity=finding.severity.value,
        confidence=finding.confidence,
        exposure="network-exposed",
        launch_risk=True,
        file=finding.evidence.file,
        line=finding.evidence.line_start,
        score=100,
        rationale="high, launch-risk surface",
    )

    class FakeLead:
        calls: list[dict] = []

        def __init__(self, repo_path: Path) -> None:
            self.repo_path = repo_path

        async def run_recon(self, **kwargs) -> SimpleNamespace:
            self.calls.append(kwargs)
            on_event = kwargs.get("on_event")
            if on_event:
                on_event("sast.payments: claude reviewing 1 file")
            if len(self.calls) == 1:
                return SimpleNamespace(
                    findings=[finding],
                    secret_hits=[],
                    warnings=[],
                    decisions=[],
                    fix_queue=[queue_item],
                )
            return SimpleNamespace(
                findings=[],
                secret_hits=[],
                warnings=[],
                decisions=[],
                fix_queue=[],
            )

    def fake_resolve(*args, **kwargs) -> PatchTarget:
        return PatchTarget(
            ok=True,
            message="Found source file `backend/app/api/billing.py`.",
            finding=finding.model_dump(mode="json"),
            files=(source,),
            evidence_file=finding.evidence.file,
        )

    async def fake_generate(*args, **kwargs) -> PatchSuggestion:
        return PatchSuggestion(
            ok=True,
            message="Patch draft ready.",
            diff=(
                "diff --git a/backend/app/api/billing.py "
                "b/backend/app/api/billing.py\n"
            ),
        )

    def fake_apply(*args, **kwargs) -> ApplyPatchResult:
        source.write_text("allow = subscription.active\n")
        return ApplyPatchResult(applied=True, message="Patch applied.")

    monkeypatch.setattr(tui, "LeadOrchestrator", FakeLead)
    monkeypatch.setattr("descry.commands.fix.resolve_patch_target", fake_resolve)
    monkeypatch.setattr("descry.commands.fix.generate_patch_suggestion", fake_generate)
    monkeypatch.setattr("descry.commands.fix.apply_patch_draft", fake_apply)

    app = SwainApp(repo_path=repo)
    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause(0.2)
        input_box = app.query_one("#message-input", Input)
        input_box.value = "/scan"
        await pilot.press("enter")

        text = ""
        for _ in range(30):
            await pilot.pause(0.1)
            text = _chat_text(app.query_one("#chat-log", ChatLog))
            if "VERDICT: READY" in text:
                break

        assert "Fixing 1 finding" in text
        assert "asking Codex" in text
        assert "applied" in text
        assert "Verifying applied fixes" in text
        assert "VERDICT: READY" in text

    assert source.read_text() == "allow = subscription.active\n"
    assert len(FakeLead.calls) == 2
    assert FakeLead.calls[0]["use_cache"] is True
    assert FakeLead.calls[1]["focus_files"] == {"backend/app/api/billing.py"}
