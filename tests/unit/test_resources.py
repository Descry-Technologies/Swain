from descry.resources import (
    builtin_playbooks_dir,
    bundled_demo_dir,
    schema_path,
    schemas_dir,
)


def test_bundled_resource_paths_resolve_in_source_checkout() -> None:
    assert (builtin_playbooks_dir() / "sast" / "tenant-isolation.yaml").exists()
    assert schemas_dir().is_dir()
    assert schema_path("playbook.v1.json").exists()
    assert (bundled_demo_dir() / ".swain" / "profile.yaml").exists()
