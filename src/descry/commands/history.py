"""Helpers for reading finding detail records from scan history."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

from descry.memory.store import MemoryStore


def lookup_finding(store: MemoryStore, finding_id: str) -> dict | None:
    """Find a finding by full ID or prefix from newest detail history first."""
    prefix = finding_id.strip()
    if not prefix:
        return None

    short_prefix = prefix[:8]
    for finding in iter_history_findings(store):
        candidate = str(finding.get("id", ""))
        if candidate.startswith(prefix) or candidate.startswith(short_prefix):
            return finding
    return None


def load_latest_findings(store: MemoryStore) -> list[dict]:
    """Return findings from the newest detail history file."""
    paths = _finding_history_paths(store)
    if not paths:
        return []
    return _read_findings(paths[0])


def iter_history_findings(store: MemoryStore) -> Iterator[dict]:
    paths = _finding_history_paths(store)
    for path in paths:
        yield from _read_findings(path)


def summary_history_paths(store: MemoryStore) -> list[Path]:
    """Return run-summary history files, newest first."""
    return sorted(
        (
            path
            for directory in _history_dirs(store)
            for path in directory.glob("*.json")
            if "findings" not in path.name
        ),
        key=_history_sort_key,
        reverse=True,
    )


def _finding_history_paths(store: MemoryStore) -> list[Path]:
    return sorted(
        (
            path
            for directory in _history_dirs(store)
            for path in directory.glob("*-findings.json")
        ),
        key=_history_sort_key,
        reverse=True,
    )


def _history_dirs(store: MemoryStore) -> list[Path]:
    dirs = [store.history_dir]
    demo_history = store.root / "demo-history"
    if demo_history.is_dir():
        dirs.append(demo_history)
    return dirs


def _read_findings(path: Path) -> list[dict]:
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return []

    if isinstance(data, list):
        findings = data
    elif isinstance(data, dict):
        findings = data.get("findings", [])
    else:
        return []

    return [finding for finding in findings if isinstance(finding, dict)]


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _history_sort_key(path: Path) -> tuple[float, str]:
    return (_mtime(path), path.name)
