import pytest

from descry.commands.scan import _to_json, _to_markdown, run_scan
from descry.memory.config import SwainConfig
from descry.memory.profile import ProjectProfile
from descry.memory.store import MemoryStore


@pytest.mark.asyncio
async def test_scan_without_profile_does_not_create_descry_dir(tmp_path) -> None:
    await run_scan(tmp_path, mock=True)

    assert not (tmp_path / ".swain").exists()


@pytest.mark.asyncio
async def test_mock_scan_does_not_persist_coworker_state(tmp_path) -> None:
    (tmp_path / "app.py").write_text("print('hello')\n")
    store = MemoryStore(tmp_path)
    ProjectProfile(
        repo_name=tmp_path.name,
        languages=["python"],
        frameworks=["fastapi"],
        deps=["fastapi"],
    ).save(store)
    SwainConfig.completed(worker_mode="claude").save(store)

    out_file = tmp_path / "scan.json"
    await run_scan(tmp_path, output="json", out_file=str(out_file), mock=True)

    assert out_file.exists()
    assert not store.mission_ledger_path.exists()
    assert not store.decision_log_path.exists()
    assert not store.fix_queue_path.exists()
    assert not store.schedule_path.exists()
    assert not list(store.history_dir.glob("*.json"))


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
