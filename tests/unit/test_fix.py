import json
from pathlib import Path

import pytest

from descry.commands.fix import (
    apply_patch_draft,
    generate_patch_suggestion,
    resolve_patch_target,
)
from descry.memory.store import MemoryStore


@pytest.mark.asyncio
async def test_fix_missing_file_explains_preflight_without_codex(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_finding_history(
        tmp_path,
        finding_id="fadc886b12345678",
        file="backend/app/missing.py",
    )

    async def fail_if_called(*args, **kwargs) -> None:
        raise AssertionError("Codex should not run when the source file is missing")

    monkeypatch.setattr(
        "descry.workers.codex_worker.CodexWorker.run_patch_diff",
        fail_if_called,
    )

    suggestion = await generate_patch_suggestion(tmp_path, "fadc886b")

    assert suggestion.ok is False
    assert "backend/app/missing.py" in suggestion.message
    assert "doesn't exist" in suggestion.message
    assert "I did not call Codex" in suggestion.message


def test_fix_resolves_file_paths_that_include_line_suffix(tmp_path: Path) -> None:
    source = tmp_path / "backend" / "app.py"
    source.parent.mkdir()
    source.write_text("print('hello')\n")
    _write_finding_history(
        tmp_path,
        finding_id="fadc886b12345678",
        file="backend/app.py:1",
    )

    target = resolve_patch_target(tmp_path, "fadc886b")

    assert target.ok is True
    assert target.files == (source,)
    assert "backend/app.py" in target.message


def test_fix_treats_unknown_file_as_unpatchable(tmp_path: Path) -> None:
    _write_finding_history(
        tmp_path,
        finding_id="fadc886b12345678",
        file="unknown",
    )

    target = resolve_patch_target(tmp_path, "fadc886b")

    assert target.ok is False
    assert "didn't name a real source file" in target.message
    assert "I did not call Codex" in target.message


def test_apply_patch_draft_applies_clean_patch(tmp_path: Path) -> None:
    source = tmp_path / "app.py"
    source.write_text("old = True\n")
    patch = tmp_path / ".swain" / "fixes" / "fadc886b.patch"
    patch.parent.mkdir(parents=True)
    patch.write_text(
        "\n".join(
            [
                "diff --git a/app.py b/app.py",
                "index 3763032..bac0ee7 100644",
                "--- a/app.py",
                "+++ b/app.py",
                "@@ -1 +1 @@",
                "-old = True",
                "+old = False",
                "",
            ]
        )
    )

    result = apply_patch_draft(tmp_path, patch)

    assert result.applied is True
    assert source.read_text() == "old = False\n"


def _write_finding_history(repo_root: Path, *, finding_id: str, file: str) -> None:
    store = MemoryStore(repo_root)
    finding = {
        "id": finding_id,
        "rule": "sast.auth.python",
        "severity": "high",
        "confidence": 0.9,
        "title": "Missing authorization check",
        "evidence": {
            "file": file,
            "line_start": 1,
            "anchor": "handler",
        },
    }
    (store.history_dir / "run123-findings.json").write_text(
        json.dumps([finding], indent=2)
    )
