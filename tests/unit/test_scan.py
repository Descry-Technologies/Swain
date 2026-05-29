import pytest

from descry.commands.scan import _to_json, _to_markdown, run_scan


@pytest.mark.asyncio
async def test_scan_without_profile_does_not_create_descry_dir(tmp_path) -> None:
    await run_scan(tmp_path, mock=True)

    assert not (tmp_path / ".swain").exists()


def test_markdown_report_does_not_claim_clean_when_playbooks_fail() -> None:
    report = _to_markdown([], [], "run123", ["sast.auth.python timed out"])

    assert "## Scan Warnings" in report
    assert "sast.auth.python timed out" in report
    assert "✅ No findings" not in report
    assert "scan was incomplete" in report


def test_json_report_marks_scan_incomplete_when_playbooks_fail() -> None:
    report = _to_json([], [], "run123", ["secrets.scan timed out"])

    assert report["complete"] is False
    assert report["warnings"] == ["secrets.scan timed out"]
