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


def test_repo_inventory_ignores_weak_payment_and_upload_words(tmp_path) -> None:
    package = tmp_path / "package.json"
    package.write_text('{"dependencies":{"react":"19.0.0"}}\n')
    page = tmp_path / "src/pages/tenant.tsx"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(
        """
export const form = {
  billing_email: "",
  radio_note: "Upload / download split"
}
"""
    )

    inventory = RepoInventory.scan(tmp_path)

    assert inventory.has_payments is False
    assert inventory.has_file_upload is False
