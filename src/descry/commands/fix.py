"""descry fix — ask Codex for a reviewed patch suggestion."""

from __future__ import annotations

import json
from pathlib import Path

from rich.console import Console
from rich.panel import Panel

from descry.commands.history import lookup_finding
from descry.memory.store import MemoryStore
from descry.workers.codex_worker import CodexWorker

console = Console()


async def run_fix(repo_root: Path, finding_id: str) -> None:
    store = MemoryStore(repo_root)
    finding = lookup_finding(store, finding_id)
    if not finding:
        console.print(f"[red]Finding not found in history: {finding_id}[/red]")
        return

    files = _relevant_files(repo_root, finding)
    if not files:
        console.print("[red]No existing repository file found for this finding.[/red]")
        return

    worker = CodexWorker()
    if not worker.is_available():
        console.print(
            "[red]codex CLI not found. Install/authenticate Codex CLI to "
            "generate fixes.[/red]"
        )
        return

    finding_label = finding.get("id", finding_id)[:8]
    console.print(
        f"[dim]Asking Codex for a patch suggestion for {finding_label}...[/dim]"
    )
    result = await worker.run_patch_diff(_build_prompt(finding), files, repo_root)
    if result.timed_out:
        console.print("[red]Codex fix generation timed out.[/red]")
        return
    if result.exit_code != 0:
        console.print(f"[yellow]Codex exited with code {result.exit_code}.[/yellow]")
        if result.stderr:
            console.print(f"[dim]{result.stderr.strip()}[/dim]")

    diff = result.stdout.strip()
    if not diff:
        console.print("[yellow]Codex did not return a patch diff.[/yellow]")
        return

    console.print(Panel.fit(diff, title="Suggested Patch Diff", border_style="cyan"))


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
You are generating a minimal security fix for one Descry finding.

Return ONLY a unified diff patch suitable for review and `git apply`.
Do not apply changes. Do not include markdown fences or explanatory text.
Keep the patch focused on this finding and preserve the existing style.

Finding:
{finding_json}
"""
