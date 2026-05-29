from descry.commands.demo import prepare_demo_repo


def test_prepare_demo_repo_copies_bundled_demo(tmp_path) -> None:
    demo = prepare_demo_repo(tmp_path / "launchpad-saas")

    assert (demo / ".swain" / "profile.yaml").exists()
    assert not (demo / ".swain" / ".local").exists()
    assert (demo / "backend" / "app" / "api" / "v1" / "billing.py").exists()
