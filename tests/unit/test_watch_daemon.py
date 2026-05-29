from pathlib import Path
from types import SimpleNamespace

import pytest
from git import Repo

from descry.commands.daemon import render_systemd_service, service_name_for_repo
from descry.commands.watch import poll_git_once, read_git_state
from descry.memory.config import SwainConfig
from descry.memory.profile import ProjectProfile
from descry.memory.store import MemoryStore


def test_systemd_service_generation_uses_swain_and_repo_path(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo with spaces"
    service = render_systemd_service(repo_root, "/usr/local/bin/swain", 17)

    assert f"Description=Swain watch for {repo_root}" in service
    assert 'WorkingDirectory="' in service
    assert '"/usr/local/bin/swain" watch' not in service
    assert "/usr/local/bin/swain watch" in service
    assert f'"{repo_root}" --interval 17' in service
    assert service_name_for_repo(repo_root).startswith("swain-watch-repo-with-spaces-")


@pytest.mark.asyncio
async def test_git_poll_detects_tracked_file_change_and_triggers_scan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = Repo.init(tmp_path)
    with repo.config_writer() as writer:
        writer.set_value("user", "name", "Swain Test")
        writer.set_value("user", "email", "swain@example.test")
    source = tmp_path / "app.py"
    source.write_text("print('one')\n")
    repo.index.add(["app.py"])
    repo.index.commit("initial")
    _init_repo_memory(tmp_path)

    calls: list[tuple[str, str, bool, bool]] = []

    class FakeLead:
        def __init__(self, repo_root: Path) -> None:
            self.repo_root = repo_root

        async def run_recon(
            self,
            *,
            trigger: str = "manual",
            objective: str = "",
            mock: bool = False,
            persist: bool = True,
        ) -> SimpleNamespace:
            calls.append((trigger, objective, mock, persist))
            return SimpleNamespace(mission_id="mission123")

    monkeypatch.setattr("descry.commands.watch.LeadOrchestrator", FakeLead)

    initial = await poll_git_once(tmp_path)
    source.write_text("print('two')\n")
    changed = await poll_git_once(tmp_path, mock=True)

    assert initial.triggered is False
    assert changed.triggered is True
    assert changed.mission_id == "mission123"
    assert calls[0][0] == "on_commit"
    assert "tracked files changed" in calls[0][1]
    assert calls[0][2] is True
    assert calls[0][3] is False


@pytest.mark.asyncio
async def test_git_poll_reports_invalid_git_repo_without_triggering(
    tmp_path: Path,
) -> None:
    (tmp_path / ".git").mkdir()
    _init_repo_memory(tmp_path)

    state = read_git_state(tmp_path)
    result = await poll_git_once(tmp_path)

    assert state.valid is False
    assert result.triggered is False
    assert result.signature == ""
    assert result.reason == "not a git repository"


def _init_repo_memory(repo_root: Path) -> None:
    store = MemoryStore(repo_root)
    ProjectProfile(
        repo_name=repo_root.name,
        languages=["python"],
        frameworks=["fastapi"],
        deps=["fastapi"],
    ).save(store)
    SwainConfig.completed(worker_mode="claude").save(store)
