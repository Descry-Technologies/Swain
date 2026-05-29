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


def iter_history_findings(store: MemoryStore) -> Iterator[dict]:
    paths = sorted(
        store.history_dir.glob("*-findings.json"),
        key=_mtime,
        reverse=True,
    )
    for path in paths:
        yield from _read_findings(path)


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
