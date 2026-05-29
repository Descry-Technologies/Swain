from pathlib import Path

import yaml

from descry.memory.profile import ProjectProfile
from descry.orchestrator.planner import Planner
from descry.playbooks.loader import PlaybookLoader
from descry.resources import builtin_playbooks_dir
from descry.scanners.inventory import RepoInventory

ROOT = Path(__file__).parents[2]
DEMO_REPO = ROOT / "examples" / "launchpad-saas"
DEMO_ASSETS = ROOT / "docs" / "assets" / "demo"


class NoSchedule:
    def get_schedules_for_trigger(self, trigger: str) -> list[dict]:
        return []

    def upsert_risk_trigger(
        self,
        playbook: str,
        paths: list[str],
        reason: str,
    ) -> None:
        return None


def test_public_demo_repo_is_initialized_for_screenshots() -> None:
    config_data = yaml.safe_load((DEMO_REPO / ".swain/config.yaml").read_text())
    profile_data = yaml.safe_load((DEMO_REPO / ".swain/profile.yaml").read_text())
    profile = ProjectProfile(**profile_data)

    assert config_data["setup"]["completed"] is True
    assert config_data["workers"]["mode"] == "hybrid"
    assert profile.repo_name == "launchpad-saas"
    assert {"react", "fastapi", "stripe"}.issubset(set(profile.frameworks))
    assert profile.has_auth is True
    assert profile.has_payments is True
    assert profile.has_file_upload is True
    assert profile.user_priorities


def test_public_demo_routes_to_launch_risk_playbooks() -> None:
    inventory = RepoInventory.scan(DEMO_REPO)
    loader = PlaybookLoader(builtin_playbooks_dir())
    mission = Planner(loader, NoSchedule()).plan("manual", inventory)
    tasks = {task.playbook_id: task for task in mission.tasks}

    expected = {
        "secrets.scan",
        "sast.auth.python",
        "sast.file-upload",
        "sast.payments",
        "sast.sql-injection",
        "sast.tenant-isolation",
        "sast.xss.react",
    }

    assert expected == set(tasks)
    assert "backend/app/api/v1/billing.py" in tasks["sast.payments"].files
    assert "backend/app/api/v1/uploads.py" in tasks["sast.file-upload"].files
    assert "backend/app/api/v1/tenants.py" in tasks["sast.tenant-isolation"].files
    assert "frontend/src/pages/Preview.tsx" in tasks["sast.xss.react"].files


def test_public_demo_assets_are_checked_in_and_scrubbed() -> None:
    expected = {
        "doctor.svg",
        "status.svg",
        "scan-mock.svg",
        "scan-flow.gif",
        "launch-card.svg",
        "tui-first-run.svg",
        "finding-narrative.svg",
        "transcript.md",
    }
    present = {path.name for path in DEMO_ASSETS.iterdir() if path.is_file()}
    transcript = (DEMO_ASSETS / "transcript.md").read_text()

    assert expected.issubset(present)
    assert str(Path.home()) not in transcript
    assert "examples/launchpad-saas" in transcript
    assert "seeded from checked-in fixture findings" in transcript
    assert "uv run swain" not in transcript
    assert "Open findings: 5" in transcript
    assert "Fix first: `bee77255`" in transcript
    assert "swain fix bee77255" in transcript
    assert (DEMO_ASSETS / "scan-flow.gif").stat().st_size > 50_000
    status_svg = (DEMO_ASSETS / "status.svg").read_text()
    assert "Fix&#160;first:&#160;`bee77255`" in status_svg
    launch_card_svg = (DEMO_ASSETS / "launch-card.svg").read_text()
    assert "BLOCKED" in launch_card_svg
    assert "bee77255" in launch_card_svg
    assert str(Path.home()) not in launch_card_svg
    assert "bee77255" in (DEMO_ASSETS / "finding-narrative.svg").read_text()


def test_public_demo_has_fix_first_history_fixture() -> None:
    fixture_path = DEMO_REPO / ".swain/demo-history/demo12345678-findings.json"
    findings = yaml.safe_load(fixture_path.read_text())

    assert findings
    assert findings[0]["id"].startswith("bee77255")
