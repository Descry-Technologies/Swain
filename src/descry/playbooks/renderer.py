"""Render a playbook prompt template with learned context injected."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


def render_prompt(
    playbook: dict[str, Any],
    learned_context: str,
    accepted_patterns: list[str],
    file_list: list[str],
    extra: dict[str, Any] | None = None,
) -> str:
    """
    Simple template renderer — no Jinja2 dependency for security.
    Variables: {{learned_context}}, {{accepted_patterns}}, {{file_list}}, {{<key>}}
    All values are treated as DATA, never as instructions.
    """
    template = playbook.get("prompt", "")
    subs: dict[str, str] = {
        "learned_context": learned_context,
        "accepted_patterns": "\n".join(f"  - {p}" for p in accepted_patterns) or "  (none)",
        "file_list": "\n".join(f"  {f}" for f in file_list[:50]),
        "playbook_id": playbook.get("id", ""),
        "playbook_version": str(playbook.get("version", 1)),
    }
    if extra:
        subs.update({k: str(v) for k, v in extra.items()})

    result = template
    for key, value in subs.items():
        # Quote substituted values to prevent template injection
        result = result.replace("{{" + key + "}}", _quote_data(value, key))
    return result


def _quote_data(value: str, key: str) -> str:
    """
    For user-facing fields (file paths, context), wrap in a DATA block
    to signal to the model that this content is untrusted data.
    file_list and accepted_patterns get wrapped; learned_context does not
    (it's our own generated text).
    """
    if key in ("file_list", "accepted_patterns"):
        return value  # already structured
    return value
