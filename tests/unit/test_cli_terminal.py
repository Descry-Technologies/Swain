import io
import sys
from pathlib import Path

import pytest

import descry.cli as cli


class _TtyBuffer(io.StringIO):
    def isatty(self) -> bool:
        return True


class _PipeBuffer(io.StringIO):
    def isatty(self) -> bool:
        return False


def test_restore_terminal_modes_disables_mouse_reporting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stdout = _TtyBuffer()
    monkeypatch.setattr(sys, "stdout", stdout)

    cli._restore_terminal_modes()

    output = stdout.getvalue()
    assert "\x1b[?1000l" in output
    assert "\x1b[?1002l" in output
    assert "\x1b[?1003l" in output
    assert "\x1b[?1006l" in output
    assert "\x1b[?2004l" in output
    assert "\x1b[?25h" in output


def test_restore_terminal_modes_falls_back_to_stderr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stdout = _PipeBuffer()
    stderr = _TtyBuffer()
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "stderr", stderr)

    cli._restore_terminal_modes()

    assert stdout.getvalue() == ""
    assert "\x1b[?1006l" in stderr.getvalue()


def test_run_tui_restores_terminal_modes_after_crash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stdout = _TtyBuffer()
    monkeypatch.setattr(sys, "stdout", stdout)

    class BrokenApp:
        def __init__(self, repo_path: Path) -> None:
            self.repo_path = repo_path

        def run(self) -> None:
            raise RuntimeError("boom")

    monkeypatch.setattr("descry.tui.app.SwainApp", BrokenApp)

    with pytest.raises(RuntimeError, match="boom"):
        cli._run_tui(tmp_path)

    assert "\x1b[?1006l" in stdout.getvalue()
