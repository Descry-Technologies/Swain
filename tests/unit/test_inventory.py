from pathlib import Path

from descry.scanners.inventory import RepoInventory

FIXTURE_REPO = Path(__file__).parents[1] / "fixtures" / "repos" / "nextjs-supabase"


def test_repo_inventory_detects_nextjs_supabase_project() -> None:
    inventory = RepoInventory.scan(FIXTURE_REPO, prev_deps=[])

    assert "TypeScript" in inventory.languages
    assert {"next", "react", "supabase"}.issubset(set(inventory.frameworks))
    assert "postgres" in inventory.db
    assert inventory.has_auth is True
    assert inventory.has_payments is True
    assert inventory.has_file_upload is True
    assert any(path.name == "route.ts" for path in inventory.route_files)
    assert "has-routes" in inventory.risk_events
