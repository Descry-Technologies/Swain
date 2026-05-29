"""Generate a shareable launch-readiness card from local Swain history."""

from __future__ import annotations

import html
import textwrap
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from rich.console import Console
from rich.panel import Panel

from descry.commands.history import load_latest_findings
from descry.memory.coworker import FixQueueItem
from descry.memory.profile import ProjectProfile
from descry.memory.store import MemoryStore
from descry.orchestrator.lead import LeadOrchestrator

console = Console()

CARD_WIDTH = 1200
CARD_HEIGHT = 630


@dataclass(frozen=True)
class LaunchCardData:
    repo_name: str
    project: str
    stack: str
    surfaces: str
    verdict: str
    verdict_summary: str
    verdict_color: str
    open_findings: int
    launch_blockers: int
    top_issue_id: str
    top_issue_title: str
    top_issue_meta: str
    next_command: str
    generated_at: str


def run_launch_card(
    repo_root: Path,
    *,
    out_path: Path | None = None,
) -> bool:
    """Write a social-ready launch card for a repo with Swain history."""
    profile_path = repo_root / ".swain" / "profile.yaml"
    if not profile_path.exists():
        console.print(
            "[yellow]No .swain/profile.yaml found. "
            "Run [bold]swain setup[/bold] or [bold]swain demo[/bold] first.[/yellow]"
        )
        return False

    output = out_path or (repo_root / "swain-launch-card.svg")
    data = build_launch_card_data(repo_root)
    write_launch_card_svg(data, output)
    console.print(
        Panel.fit(
            "\n".join([
                f"[bold]{data.verdict}[/bold]: {data.verdict_summary}",
                f"Open findings: {data.open_findings}",
                f"Launch blockers: {data.launch_blockers}",
                f"Top issue: {data.top_issue_id or 'none'}",
                f"Wrote: {output}",
            ]),
            title="Swain Launch Card",
        )
    )
    return True


def build_launch_card_data(
    repo_root: Path,
    *,
    generated_at: datetime | None = None,
) -> LaunchCardData:
    store = MemoryStore(repo_root)
    profile = ProjectProfile.load(store)
    raw_findings = load_latest_findings(store)
    open_findings = [
        finding for finding in raw_findings
        if finding.get("lifecycle", {}).get("status", "open") == "open"
    ]
    queue = LeadOrchestrator(repo_root).build_fix_queue_from_history(store)
    blockers = [
        item for item in queue
        if item.severity in {"critical", "high"} and item.launch_risk
    ]
    top_issue = _top_issue(queue, blockers)
    verdict, summary, color = _verdict(
        has_history=bool(raw_findings),
        open_count=len(open_findings),
        blocker_count=len(blockers),
    )

    return LaunchCardData(
        repo_name=profile.repo_name or repo_root.name,
        project=_clean(profile.app_purpose or profile.repo_name or repo_root.name),
        stack=", ".join(profile.frameworks or profile.languages) or "unknown stack",
        surfaces=", ".join(_surfaces(profile)) or "repo code",
        verdict=verdict,
        verdict_summary=summary,
        verdict_color=color,
        open_findings=len(open_findings),
        launch_blockers=len(blockers),
        top_issue_id=top_issue.finding_id[:8] if top_issue else "",
        top_issue_title=(
            top_issue.title if top_issue else _empty_top_issue(raw_findings)
        ),
        top_issue_meta=_top_issue_meta(top_issue),
        next_command=_next_command(repo_root, top_issue, raw_findings),
        generated_at=(generated_at or datetime.now(UTC)).strftime(
            "%Y-%m-%d %H:%M UTC"
        ),
    )


def write_launch_card_svg(data: LaunchCardData, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_render_svg(data))


def _top_issue(
    queue: list[FixQueueItem],
    blockers: list[FixQueueItem],
) -> FixQueueItem | None:
    if blockers:
        return blockers[0]
    return queue[0] if queue else None


def _verdict(
    *,
    has_history: bool,
    open_count: int,
    blocker_count: int,
) -> tuple[str, str, str]:
    if not has_history:
        return (
            "NO SCAN YET",
            "Run a scan before posting a launch verdict.",
            "#9aa4b2",
        )
    if blocker_count:
        return (
            "BLOCKED",
            "Fix launch blockers before shipping.",
            "#ff5a5f",
        )
    if open_count:
        return (
            "REVIEW",
            "Review open findings before launch.",
            "#f0b429",
        )
    return (
        "READY",
        "No open findings in the latest scan history.",
        "#2fdd92",
    )


def _surfaces(profile: ProjectProfile) -> list[str]:
    return [
        label for label, enabled in [
            ("auth", profile.has_auth),
            ("payments", profile.has_payments),
            ("uploads", profile.has_file_upload),
            ("LLM features", profile.has_llm_features),
        ] if enabled
    ]


def _empty_top_issue(raw_findings: list[dict]) -> str:
    if raw_findings:
        return "No open issue selected"
    return "No scan history yet"


def _top_issue_meta(item: FixQueueItem | None) -> str:
    if not item:
        return "Swain needs a scan before it can rank launch risk."
    location = item.file
    if item.line:
        location = f"{location}:{item.line}"
    return f"{item.severity.upper()} - {item.confidence:.0%} confidence - {location}"


def _next_command(
    repo_root: Path,
    item: FixQueueItem | None,
    raw_findings: list[dict],
) -> str:
    repo_arg = _display_repo_arg(repo_root)
    if item:
        return f"swain fix {item.finding_id[:8]} --path {repo_arg}"
    if raw_findings:
        return f"swain status {repo_arg}"
    return f"swain scan {repo_arg}"


def _display_repo_arg(repo_root: Path) -> str:
    cwd = Path.cwd().resolve()
    try:
        relative = repo_root.resolve().relative_to(cwd)
    except ValueError:
        return str(repo_root)
    if str(relative) == ".":
        return "."
    return str(relative)


def _render_svg(data: LaunchCardData) -> str:
    project_lines = _wrap(data.project, 48, 2)
    top_lines = _wrap(data.top_issue_title, 28, 3)
    top_meta_lines = _wrap(data.top_issue_meta, 42, 2)
    command_lines = _wrap(data.next_command, 76, 2)
    subtitle = f"{data.stack} - {data.surfaces}"
    subtitle_lines = _wrap(subtitle, 58, 2)

    return "\n".join([
        '<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630" '
        'viewBox="0 0 1200 630" role="img" aria-label="Swain launch card">',
        "<defs>",
        '<linearGradient id="accent" x1="0" x2="1" y1="0" y2="1">',
        '<stop offset="0" stop-color="#2fdd92"/>',
        '<stop offset="0.55" stop-color="#31c6f7"/>',
        '<stop offset="1" stop-color="#f0b429"/>',
        "</linearGradient>",
        '<filter id="shadow" x="-10%" y="-10%" width="120%" height="120%">',
        '<feDropShadow dx="0" dy="12" stdDeviation="18" flood-color="#000" '
        'flood-opacity="0.35"/>',
        "</filter>",
        "</defs>",
        '<rect width="1200" height="630" fill="#101214"/>',
        '<rect x="34" y="34" width="1132" height="562" rx="28" fill="#15191d" '
        'stroke="#263039" filter="url(#shadow)"/>',
        '<rect x="34" y="34" width="1132" height="10" rx="5" fill="url(#accent)"/>',
        _text("Swain Launch Check", 72, 86, 24, "#2fdd92", weight=700),
        _text(data.repo_name, 72, 122, 19, "#9aa4b2"),
        _text(data.verdict, 72, 202, 72, data.verdict_color, weight=800),
        _text(data.verdict_summary, 76, 244, 28, "#f3f6f4", weight=650),
        *_text_block(project_lines, 76, 292, 24, "#cfd8d3", line_height=31),
        *_text_block(subtitle_lines, 76, 372, 18, "#8f9aa3", line_height=26),
        _metric_card(
            748,
            82,
            "Open findings",
            str(data.open_findings),
            "#31c6f7",
        ),
        _metric_card(
            956,
            82,
            "Launch blockers",
            str(data.launch_blockers),
            data.verdict_color,
        ),
        '<rect x="724" y="226" width="382" height="198" rx="18" '
        'fill="#101418" stroke="#2c3741"/>',
        _text("Fix first", 752, 266, 18, "#8f9aa3", weight=650),
        _text(
            data.top_issue_id or "none",
            976,
            266,
            18,
            data.verdict_color,
            weight=700,
        ),
        *_text_block(top_lines, 752, 306, 25, "#f3f6f4", line_height=32),
        *_text_block(top_meta_lines, 752, 388, 15, "#9aa4b2", line_height=21),
        '<rect x="72" y="468" width="1034" height="72" rx="18" '
        'fill="#0f1715" stroke="#28443b"/>',
        _text("Next", 100, 511, 18, "#2fdd92", weight=700),
        *_text_block(command_lines, 166, 511, 20, "#f3f6f4", line_height=27),
        _text(
            "review-only patch drafts - no source edits are applied",
            72,
            574,
            16,
            "#7f8a92",
        ),
        _text(data.generated_at, 952, 574, 16, "#7f8a92"),
        "</svg>",
        "",
    ])


def _metric_card(
    x: int,
    y: int,
    label: str,
    value: str,
    color: str,
) -> str:
    return "\n".join([
        f'<rect x="{x}" y="{y}" width="150" height="104" rx="18" '
        'fill="#101418" stroke="#2c3741"/>',
        _text(value, x + 26, y + 58, 44, color, weight=800),
        _text(label, x + 26, y + 86, 15, "#9aa4b2"),
    ])


def _text(
    text: str,
    x: int,
    y: int,
    size: int,
    color: str,
    *,
    weight: int = 500,
) -> str:
    return (
        f'<text x="{x}" y="{y}" fill="{color}" '
        'font-family="Inter, ui-sans-serif, system-ui, -apple-system, '
        f'Segoe UI, sans-serif" font-size="{size}" font-weight="{weight}">'
        f"{html.escape(text)}</text>"
    )


def _text_block(
    lines: list[str],
    x: int,
    y: int,
    size: int,
    color: str,
    *,
    line_height: int,
) -> list[str]:
    return [
        _text(line, x, y + index * line_height, size, color)
        for index, line in enumerate(lines)
    ]


def _wrap(text: str, width: int, max_lines: int) -> list[str]:
    lines = textwrap.wrap(_clean(text), width=width) or [""]
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip(".") + "..."
    return lines


def _clean(text: str) -> str:
    return " ".join(str(text).replace("\n", " ").split())
