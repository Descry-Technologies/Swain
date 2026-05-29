from pathlib import Path

from descry.orchestrator.planner import Planner
from descry.playbooks.loader import PlaybookLoader
from descry.playbooks.renderer import render_prompt
from descry.resources import builtin_playbooks_dir
from descry.scanners.inventory import RepoInventory

ROOT = Path(__file__).parents[2]
LAUNCH_RISK_REPO = ROOT / "tests" / "fixtures" / "repos" / "launch-risk-saas"


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


def test_builtin_playbooks_validate_against_schema() -> None:
    loader = PlaybookLoader(builtin_playbooks_dir())

    playbook_ids = {playbook["id"] for playbook in loader.load_all()}

    assert "sast.file-upload" in playbook_ids
    assert "sast.payments" in playbook_ids
    assert "sast.tenant-isolation" in playbook_ids


def test_launch_risk_fixture_routes_to_relevant_playbooks() -> None:
    loader = PlaybookLoader(builtin_playbooks_dir())
    inventory = RepoInventory.scan(LAUNCH_RISK_REPO)
    mission = Planner(loader, NoSchedule()).plan("manual", inventory)
    tasks = {task.playbook_id: task for task in mission.tasks}

    expected_files = {
        "sast.auth.python": "backend/app/api/v1/tenants.py",
        "sast.tenant-isolation": "backend/app/api/v1/tenants.py",
        "sast.payments": "backend/app/api/v1/billing.py",
        "sast.file-upload": "backend/app/api/v1/uploads.py",
        "sast.sql-injection": "backend/app/db/queries.py",
        "sast.xss.react": "frontend/src/pages/Preview.tsx",
    }

    assert set(expected_files).issubset(tasks)
    for playbook_id, expected_file in expected_files.items():
        assert expected_file in tasks[playbook_id].files


def test_launch_risk_prompts_name_the_expected_vulnerability_classes() -> None:
    loader = PlaybookLoader(builtin_playbooks_dir())
    playbooks = {playbook["id"]: playbook for playbook in loader.load_all()}

    checks = {
        "sast.auth.python": ["authorization", "IDOR"],
        "sast.tenant-isolation": ["tenant_id", "membership/ownership"],
        "sast.payments": ["webhook signature", "client-supplied price"],
        "sast.file-upload": ["Path traversal", "size limits"],
        "sast.sql-injection": ["string concatenation", "parameterized"],
        "sast.xss.react": ["dangerouslySetInnerHTML", "sanitizer"],
    }

    for playbook_id, terms in checks.items():
        prompt = render_prompt(
            playbook=playbooks[playbook_id],
            learned_context="TEST CONTEXT",
            accepted_patterns=[],
            file_list=["example.py"],
        )
        for term in terms:
            assert term in prompt


def test_planner_ranks_relevant_files_before_applying_file_cap(tmp_path) -> None:
    for index in range(5):
        filler = tmp_path / f"scripts/filler_{index}.py"
        filler.parent.mkdir(parents=True, exist_ok=True)
        filler.write_text("print('not security relevant')\n")
    auth_file = tmp_path / "backend/app/services/auth_service.py"
    auth_file.parent.mkdir(parents=True, exist_ok=True)
    auth_file.write_text("def login(): pass\n")

    inventory = RepoInventory.scan(tmp_path)
    planner = Planner(PlaybookLoader(builtin_playbooks_dir()), NoSchedule())
    files = planner._resolve_files(
        {
            "id": "sast.auth.python",
            "files": {"include": ["**/*.py"], "max_files": 2},
        },
        inventory,
    )

    assert files[0] == "backend/app/services/auth_service.py"
    assert len(files) == 2


def test_planner_never_sends_local_secret_files_to_model_workers(tmp_path) -> None:
    (tmp_path / ".env").write_text("SECRET_KEY=real\n")
    safe_file = tmp_path / "backend/app/config.py"
    safe_file.parent.mkdir(parents=True, exist_ok=True)
    safe_file.write_text("SECRET_KEY = 'from-env'\n")

    inventory = RepoInventory.scan(tmp_path)
    planner = Planner(PlaybookLoader(builtin_playbooks_dir()), NoSchedule())
    files = planner._resolve_files(
        {
            "id": "secrets.scan",
            "files": {"include": ["**/*.py", "**/.env"], "max_files": 10},
        },
        inventory,
    )

    assert "backend/app/config.py" in files
    assert ".env" not in files
