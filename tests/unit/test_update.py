from pathlib import Path

from descry.commands.update import run_update


def test_update_reports_missing_managed_source(tmp_path: Path) -> None:
    missing = tmp_path / "missing-source"

    assert run_update(source_dir=missing, check_only=True) is False
