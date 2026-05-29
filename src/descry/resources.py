"""Helpers for locating Swain's bundled data files."""

from __future__ import annotations

from pathlib import Path


def builtin_playbooks_dir() -> Path:
    return _data_dir("playbooks")


def schemas_dir() -> Path:
    return _data_dir("schemas")


def examples_dir() -> Path:
    return _data_dir("examples")


def bundled_demo_dir() -> Path:
    demo = examples_dir() / "launchpad-saas"
    if not (demo / ".swain" / "profile.yaml").exists():
        raise FileNotFoundError(
            "Could not find bundled launchpad-saas demo. Reinstall Swain."
        )
    return demo


def schema_path(name: str) -> Path:
    return schemas_dir() / name


def _data_dir(name: str) -> Path:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / name
        if _looks_like_data_dir(candidate, name):
            return candidate
    raise FileNotFoundError(
        f"Could not find bundled {name!r}. Reinstall Swain or run from source."
    )


def _looks_like_data_dir(path: Path, name: str) -> bool:
    if not path.is_dir():
        return False
    if name == "playbooks":
        return any(path.rglob("*.yaml"))
    if name == "schemas":
        return any(path.glob("*.json"))
    if name == "examples":
        return (path / "launchpad-saas" / ".swain" / "profile.yaml").exists()
    return True
