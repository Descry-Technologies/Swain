"""Load and validate playbooks from disk."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from jsonschema import ValidationError, validate  # type: ignore[import-untyped]

from descry.resources import schema_path


class PlaybookLoader:
    def __init__(self, builtin_dir: Path, user_dir: Path | None = None) -> None:
        self.builtin_dir = builtin_dir
        self.user_dir = user_dir
        self._schema: dict[str, Any] | None = None

    def _load_schema(self) -> dict[str, Any]:
        if self._schema is None:
            path = schema_path("playbook.v1.json")
            if path.exists():
                import json

                self._schema = json.loads(path.read_text())
            else:
                self._schema = {}
        return self._schema

    def load_all(self) -> list[dict[str, Any]]:
        playbooks: list[dict[str, Any]] = []
        dirs = [self.builtin_dir]
        if self.user_dir:
            # User playbooks override built-ins with same ID
            dirs.extend([
                self.user_dir / "active",
                self.user_dir / "generated",
            ])
        for d in dirs:
            if not d.exists():
                continue
            for f in sorted(d.rglob("*.yaml")):
                try:
                    pb = yaml.safe_load(f.read_text())
                    if pb and isinstance(pb, dict):
                        self._validate(pb, f)
                        playbooks.append(pb)
                except Exception as e:
                    print(f"[swain] Warning: could not load playbook {f.name}: {e}")
        # Deduplicate: user playbooks win over built-ins
        seen: dict[str, dict[str, Any]] = {}
        for pb in playbooks:
            seen[pb.get("id", "")] = pb
        return list(seen.values())

    def _validate(self, pb: dict[str, Any], path: Path) -> None:
        schema = self._load_schema()
        if not schema:
            return
        try:
            validate(instance=pb, schema=schema)
        except ValidationError as e:
            raise ValueError(f"Invalid playbook {path.name}: {e.message}") from e

    def filter_applicable(
        self,
        playbooks: list[dict[str, Any]],
        inventory: Any,
    ) -> list[dict[str, Any]]:
        """Return playbooks that apply to the current repo inventory."""
        result: list[dict[str, Any]] = []
        for pb in playbooks:
            cond = pb.get("applies_when", {})
            if not cond:
                result.append(pb)
                continue
            deps_lower = {d.lower() for d in (inventory.deps or [])}
            any_dep = cond.get("any_dep", [])
            if any_dep and not any(d.lower() in deps_lower for d in any_dep):
                continue
            if cond.get("has_auth") and not inventory.has_auth:
                continue
            if cond.get("has_payments") and not inventory.has_payments:
                continue
            if cond.get("has_file_upload") and not inventory.has_file_upload:
                continue
            result.append(pb)
        return result
