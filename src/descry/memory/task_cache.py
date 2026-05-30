"""Persistent worker-result cache keyed by task inputs."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from descry.models import Task, WorkerReport
from descry.workers.base import WorkerResult

_HASH_CHUNK_SIZE = 65536
_CACHE_SCHEMA_VERSION = 1


class TaskResultCache:
    """Caches expensive worker calls when task inputs are unchanged."""

    def __init__(self, cache_dir: Path) -> None:
        self.cache_dir = cache_dir

    def key_for(
        self,
        *,
        task: Task,
        prompt: str,
        files: list[Path],
        repo_root: Path,
    ) -> str:
        sha = hashlib.sha256()
        _hash_text(sha, f"schema:{_CACHE_SCHEMA_VERSION}")
        _hash_text(sha, f"worker:{task.worker.value}")
        _hash_text(sha, f"playbook:{task.playbook_id}")
        _hash_text(sha, f"version:{task.context.get('playbook_version', 1)}")
        _hash_text(sha, f"prompt:{prompt}")

        root = repo_root.resolve()
        for file in sorted(files, key=lambda path: _display_path(root, path)):
            rel = _display_path(root, file)
            _hash_text(sha, f"path:{rel}")
            _hash_text(sha, f"content:{_file_hash(file)}")
        return sha.hexdigest()

    def read(self, key: str) -> WorkerResult | None:
        path = self.cache_dir / f"{key}.json"
        if not path.is_file():
            return None
        try:
            raw = json.loads(path.read_text())
            if raw.get("schema_version") != _CACHE_SCHEMA_VERSION:
                return None
            report_data = raw.get("report")
            report = (
                WorkerReport.model_validate(report_data)
                if isinstance(report_data, dict)
                else None
            )
            return WorkerResult(
                report=report,
                stderr=str(raw.get("stderr") or ""),
                exit_code=int(raw.get("exit_code") or 0),
                timed_out=bool(raw.get("timed_out")),
                parse_error=str(raw.get("parse_error") or ""),
            )
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return None

    def write(self, key: str, result: WorkerResult) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {
            "schema_version": _CACHE_SCHEMA_VERSION,
            "report": (
                result.report.model_dump(mode="json") if result.report else None
            ),
            "stderr": result.stderr,
            "exit_code": result.exit_code,
            "timed_out": result.timed_out,
            "parse_error": result.parse_error,
        }
        path = self.cache_dir / f"{key}.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True))
        tmp.replace(path)


def _hash_text(sha: Any, value: str) -> None:
    sha.update(value.encode())
    sha.update(b"\0")


def _file_hash(path: Path) -> str:
    if not path.is_file():
        return "missing"
    sha = hashlib.sha256()
    try:
        with path.open("rb") as f:
            while chunk := f.read(_HASH_CHUNK_SIZE):
                sha.update(chunk)
    except OSError:
        return "unreadable"
    return sha.hexdigest()


def _display_path(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()
