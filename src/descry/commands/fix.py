"""swain fix — ask Codex for a reviewed patch suggestion."""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
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


@dataclass(frozen=True)
class ApplyPatchResult:
    applied: bool
    message: str
    exit_code: int = 0


@dataclass(frozen=True)
class CachedFixAttempt:
    finding_id: str
    message: str
    outcome: str
    patch_path: Path | None = None
    updated_at: str = ""


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
    if _is_unknown_file(evidence_file):
        return PatchTarget(
            ok=False,
            finding=finding,
            message=(
                f"Couldn't draft `{label}`: the scan finding didn't name a "
                "real source file. I did not call Codex. Run `/scan` again to "
                "refresh the queue; if this repeats, open `/scan details` "
                "because the worker output is missing file evidence."
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


def cached_failed_fix_attempt(
    repo_root: Path,
    finding_id: str,
    target: PatchTarget,
) -> CachedFixAttempt | None:
    fingerprint = _patch_target_fingerprint(repo_root, finding_id, target)
    raw = _load_fix_attempts(repo_root).get("attempts", {}).get(fingerprint)
    if not isinstance(raw, dict) or raw.get("applied"):
        return None
    patch = raw.get("patch_path")
    patch_path = repo_root / patch if isinstance(patch, str) and patch else None
    return CachedFixAttempt(
        finding_id=str(raw.get("finding_id") or finding_id),
        message=str(raw.get("message") or "previous fix attempt failed"),
        outcome=str(raw.get("outcome") or "failed"),
        patch_path=patch_path,
        updated_at=str(raw.get("updated_at") or ""),
    )


def record_fix_attempt(
    repo_root: Path,
    finding_id: str,
    target: PatchTarget,
    *,
    applied: bool,
    message: str,
    outcome: str,
    patch_path: Path | None = None,
) -> None:
    store = MemoryStore(repo_root)
    data = _load_fix_attempts(repo_root)
    attempts = data.setdefault("attempts", {})
    if not isinstance(attempts, dict):
        attempts = {}
        data["attempts"] = attempts

    relative_patch = ""
    if patch_path is not None:
        try:
            relative_patch = patch_path.relative_to(repo_root).as_posix()
        except ValueError:
            relative_patch = patch_path.as_posix()

    attempts[_patch_target_fingerprint(repo_root, finding_id, target)] = {
        "finding_id": finding_id,
        "applied": applied,
        "message": message,
        "outcome": outcome,
        "patch_path": relative_patch,
        "updated_at": datetime.now(UTC).isoformat(),
    }
    data["updated_at"] = datetime.now(UTC).isoformat()
    store.write_json(store.fix_attempts_path, data)


def apply_patch_draft(repo_root: Path, patch_path: Path) -> ApplyPatchResult:
    """Apply a saved patch only if git says it applies cleanly."""
    check = _run_git_apply(repo_root, patch_path, check_only=True)
    if check.returncode != 0:
        return ApplyPatchResult(
            applied=False,
            message=_git_apply_message(check, "Patch did not apply cleanly."),
            exit_code=check.returncode,
        )

    apply = _run_git_apply(repo_root, patch_path, check_only=False)
    if apply.returncode != 0:
        return ApplyPatchResult(
            applied=False,
            message=_git_apply_message(apply, "Patch apply failed."),
            exit_code=apply.returncode,
        )
    return ApplyPatchResult(applied=True, message="Patch applied.")


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


def _is_unknown_file(value: str) -> bool:
    return value.strip().lower() in {"", "unknown", "n/a", "none", "null"}


def _display_file(repo_root: Path, file: Path) -> str:
    try:
        return file.relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return str(file)


def _load_fix_attempts(repo_root: Path) -> dict[str, Any]:
    store = MemoryStore(repo_root)
    return store.read_json(store.fix_attempts_path)


def _patch_target_fingerprint(
    repo_root: Path,
    finding_id: str,
    target: PatchTarget,
) -> str:
    root = repo_root.resolve()
    sha = hashlib.sha256()
    _fingerprint_text(sha, finding_id[:16])
    _fingerprint_text(sha, target.evidence_file)
    for file in sorted(target.files, key=lambda path: _display_file(root, path)):
        _fingerprint_text(sha, _display_file(root, file))
        _fingerprint_text(sha, _content_hash(file))
    return sha.hexdigest()


def _fingerprint_text(sha: Any, value: str) -> None:
    sha.update(value.encode())
    sha.update(b"\0")


def _content_hash(path: Path) -> str:
    if not path.is_file():
        return "missing"
    sha = hashlib.sha256()
    try:
        with path.open("rb") as f:
            while chunk := f.read(65536):
                sha.update(chunk)
    except OSError:
        return "unreadable"
    return sha.hexdigest()


def _run_git_apply(
    repo_root: Path,
    patch_path: Path,
    *,
    check_only: bool,
) -> subprocess.CompletedProcess[str]:
    cmd = ["git", "apply"]
    if check_only:
        cmd.append("--check")
    cmd.append(str(patch_path))
    return subprocess.run(  # noqa: S603,S607 - fixed git command.
        cmd,
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=15,
    )


def _git_apply_message(
    result: subprocess.CompletedProcess[str],
    fallback: str,
) -> str:
    detail = (result.stderr or result.stdout or "").strip().splitlines()
    return f"{fallback} {detail[0]}" if detail else fallback


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
