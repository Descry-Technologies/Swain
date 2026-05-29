from pathlib import Path

import pytest

from descry.commands.doctor import (
    _check_profile,
    _is_generated_artifact,
    _status_label,
    collect_checks,
)


def test_profile_check_guides_first_run_when_missing(tmp_path: Path) -> None:
    check = _check_profile(tmp_path)

    assert check.status == "warn"
    assert "swain setup" in check.next_step


def test_profile_check_passes_when_profile_exists(tmp_path: Path) -> None:
    profile = tmp_path / ".swain" / "profile.yaml"
    profile.parent.mkdir()
    profile.write_text("repo_name: demo\n")

    check = _check_profile(tmp_path)

    assert check.status == "ok"


def test_generated_artifact_detection() -> None:
    assert _is_generated_artifact("src/descry/__pycache__/cli.cpython-312.pyc")
    assert _is_generated_artifact("src/descry/models.pyc")
    assert not _is_generated_artifact("src/descry/models.py")


def test_status_labels_are_colored_for_terminal_output() -> None:
    assert "green" in _status_label("ok")
    assert "yellow" in _status_label("warn")
    assert "red" in _status_label("error")


@pytest.mark.asyncio
async def test_collect_checks_can_skip_worker_probes(tmp_path: Path) -> None:
    checks = await collect_checks(tmp_path, probe_workers=False)

    names = {check.name for check in checks}
    assert {"repo", "profile", "playbooks", "package hygiene"}.issubset(names)
    assert not (tmp_path / ".swain").exists()
