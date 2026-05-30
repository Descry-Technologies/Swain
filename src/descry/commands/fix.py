"""swain fix — ask Codex for a reviewed patch suggestion."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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


@dataclass(frozen=True)
class PatchTarget:
    ok: bool
    message: str
    finding: dict[str, Any] | None = None
    files: tuple[Path, ...] = ()
    evidence_file: str = ""


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
    *,
    show_status: bool = True,
    target: PatchTarget | None = None,
) -> PatchSuggestion:
    target = target or resolve_patch_target(repo_root, finding_id)
    if not target.ok:
        return PatchSuggestion(
            ok=False,
            message=target.message,
        )
    finding = target.finding or {}
    files = list(target.files)

    store = MemoryStore(repo_root)
    config = SwainConfig.load(store)
    worker = CodexWorker(
        timeout_s=config.cli_task_timeout_s,
        model=config.codex_model or None,
    )
    if not worker.is_available():
        return PatchSuggestion(
            ok=False,
            message=(
                "codex CLI not found. Install/authenticate Codex CLI to "
                "generate fixes."
            ),
        )

    finding_label = finding.get("id", finding_id)[:8]
    if show_status:
        from rich.status import Status

        with Status(
            f"[dim]Asking Codex for a patch suggestion for {finding_label}…[/dim]",
            console=console,
        ):
            result = await worker.run_patch_diff(
                _build_prompt(finding),
                files,
                repo_root,
            )
    else:
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


def resolve_patch_target(repo_root: Path, finding_id: str) -> PatchTarget:
    store = MemoryStore(repo_root)
    finding = lookup_finding(store, finding_id)
    label = finding_id.strip()[:8] or finding_id
    if not finding:
        return PatchTarget(
            ok=False,
            message=(
                f"Couldn't draft `{label}`: I couldn't find that finding in "
                "local scan history. I did not call Codex. Run `/scan` to "
                "refresh the queue."
            ),
        )

    evidence = finding.get("evidence", {})
    if not isinstance(evidence, dict):
        return PatchTarget(
            ok=False,
            finding=finding,
            message=(
                f"Couldn't draft `{label}`: the finding has no file evidence, "
                "so I don't know what to patch. I did not call Codex. Run "
                "`/scan` to refresh it."
            ),
        )
    evidence_file = str(evidence.get("file") or "").strip()
    if not evidence_file:
        return PatchTarget(
            ok=False,
            finding=finding,
            message=(
                f"Couldn't draft `{label}`: the finding doesn't name a source "
                "file. I did not call Codex. Run `/scan` to refresh it."
            ),
        )

    file = _resolve_existing_file(repo_root, evidence_file)
    if file is None:
        return PatchTarget(
            ok=False,
            finding=finding,
            evidence_file=evidence_file,
            message=(
                f"Couldn't draft `{label}`: the finding points at "
                f"`{evidence_file}`, but that file doesn't exist in "
                f"`{repo_root.name}`. I did not call Codex. Run `/scan` to "
                "refresh the queue, or open the repo that produced this finding."
            ),
        )

    return PatchTarget(
        ok=True,
        message=f"Found source file `{_display_file(repo_root, file)}`.",
        finding=finding,
        files=(file,),
        evidence_file=evidence_file,
    )


def write_patch_draft(repo_root: Path, finding_id: str, diff: str) -> Path:
    """Persist a patch draft under .swain without touching source files."""
    drafts_dir = repo_root / ".swain" / "fixes"
    drafts_dir.mkdir(parents=True, exist_ok=True)
    patch_path = drafts_dir / f"{finding_id[:8]}.patch"
    patch_path.write_text(diff.rstrip() + "\n")
    return patch_path


def _resolve_existing_file(repo_root: Path, evidence_file: str) -> Path | None:
    root = repo_root.resolve()
    candidates = [evidence_file]
    if ":" in evidence_file:
        path_part, _, line_part = evidence_file.rpartition(":")
        if path_part and line_part.isdigit():
            candidates.append(path_part)

    for rel_file in candidates:
        candidate = (root / rel_file).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            continue
        if candidate.is_file():
            return candidate
    return None


def _display_file(repo_root: Path, file: Path) -> str:
    try:
        return file.relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return str(file)


def _build_prompt(finding: dict[str, Any]) -> str:
    finding_json = json.dumps(finding, indent=2)
    return f"""\
You are generating a minimal security fix for one Swain finding.

Return ONLY a unified diff patch suitable for review and `git apply`.
Do not apply changes. Do not include markdown fences or explanatory text.
Keep the patch focused on this finding and preserve the existing style.

Finding:
{finding_json}
"""
