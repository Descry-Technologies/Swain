"""swain fix — ask Codex for a reviewed patch suggestion."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from rich.console import Console
from rich.panel import Panel

from descry.commands.history import lookup_finding
from descry.memory.config import SwainConfig
from descry.memory.store import MemoryStore
from descry.workers.codex_worker import CodexWorker

console = Console()


@dataclass(frozen=True)
class PatchSuggestion:
    ok: bool
    message: str
    diff: str = ""
    exit_code: int = 0


async def run_fix(repo_root: Path, finding_id: str) -> None:
    suggestion = await generate_patch_suggestion(repo_root, finding_id)
    if not suggestion.ok:
        style = "red" if suggestion.exit_code == 0 else "yellow"
        console.print(f"[{style}]{suggestion.message}[/{style}]")
        return

    console.print(
        Panel.fit(
            suggestion.diff,
            title="Suggested Patch Diff",
            border_style="cyan",
        )
    )


async def generate_patch_suggestion(
    repo_root: Path,
    finding_id: str,
) -> PatchSuggestion:
    store = MemoryStore(repo_root)
    finding = lookup_finding(store, finding_id)
    if not finding:
        return PatchSuggestion(
            ok=False,
            message=f"Finding not found in history: {finding_id}",
        )

    files = _relevant_files(repo_root, finding)
    if not files:
        return PatchSuggestion(
            ok=False,
            message="No existing repository file found for this finding.",
        )

    config = SwainConfig.load(store)
    worker = CodexWorker(model=config.codex_model or None)
    if not worker.is_available():
        return PatchSuggestion(
            ok=False,
            message=(
                "codex CLI not found. Install/authenticate Codex CLI to "
                "generate fixes."
            ),
        )

    finding_label = finding.get("id", finding_id)[:8]
    console.print(
        f"[dim]Asking Codex for a patch suggestion for {finding_label}...[/dim]"
    )
    result = await worker.run_patch_diff(_build_prompt(finding), files, repo_root)
    if result.timed_out:
        return PatchSuggestion(
            ok=False,
            message="Codex fix generation timed out.",
            exit_code=-1,
        )
    if result.exit_code != 0:
        message = f"Codex exited with code {result.exit_code}."
        if result.stderr:
            message = f"{message} {result.stderr.strip()}"
        return PatchSuggestion(
            ok=False,
            message=message,
            exit_code=result.exit_code,
        )

    diff = result.stdout.strip()
    if not diff:
        return PatchSuggestion(
            ok=False,
            message="Codex did not return a patch diff.",
        )

    return PatchSuggestion(ok=True, message="Patch draft ready.", diff=diff)


def _relevant_files(repo_root: Path, finding: dict) -> list[Path]:
    rel_file = finding.get("evidence", {}).get("file", "")
    if not rel_file:
        return []

    root = repo_root.resolve()
    candidate = (root / rel_file).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return []

    if not candidate.is_file():
        return []
    return [candidate]


def _build_prompt(finding: dict) -> str:
    finding_json = json.dumps(finding, indent=2)
    return f"""\
You are generating a minimal security fix for one Swain finding.

Return ONLY a unified diff patch suitable for review and `git apply`.
Do not apply changes. Do not include markdown fences or explanatory text.
Keep the patch focused on this finding and preserve the existing style.

Finding:
{finding_json}
"""
