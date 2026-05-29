from pathlib import Path

from descry.commands.update import _default_bin_dir, run_update


def test_update_reports_missing_managed_source(tmp_path: Path) -> None:
    missing = tmp_path / "missing-source"

    assert run_update(source_dir=missing, check_only=True) is False


def test_update_default_bin_dir_uses_stable_user_bin(
    tmp_path: Path, monkeypatch
) -> None:
    transient_bin = tmp_path / "transient-bin"
    transient_bin.mkdir()
    monkeypatch.delenv("SWAIN_BIN_DIR", raising=False)
    monkeypatch.setenv("PATH", str(transient_bin))

    assert _default_bin_dir() == Path.home() / ".local" / "bin"
