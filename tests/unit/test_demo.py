import json

import pytest

from descry.commands.demo import prepare_demo_repo
from descry.commands.scan import run_scan


def test_prepare_demo_repo_copies_bundled_demo(tmp_path) -> None:
    demo = prepare_demo_repo(tmp_path / "launchpad-saas")

    assert (demo / ".swain" / "profile.yaml").exists()
    assert not (demo / ".swain" / ".local").exists()
    assert (demo / "backend" / "app" / "api" / "v1" / "billing.py").exists()


@pytest.mark.asyncio
async def test_demo_mock_scan_replays_bundled_findings(tmp_path) -> None:
    demo = prepare_demo_repo(tmp_path / "launchpad-saas")
    out_file = tmp_path / "scan.json"

    await run_scan(demo, output="json", out_file=str(out_file), mock=True)

    report = json.loads(out_file.read_text())
    assert report["finding_count"] == 5
    assert any(
        finding["id"].startswith("bee77255")
        for finding in report["findings"]
    )
