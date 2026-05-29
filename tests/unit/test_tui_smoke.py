from pathlib import Path

import pytest
from textual.widgets import Input

import descry.tui.app as tui
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
