"""Generate a shareable launch-readiness card from local Swain history."""

from __future__ import annotations

import html
import textwrap
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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


def _empty_top_issue(raw_findings: list[dict[str, Any]]) -> str:
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
    raw_findings: list[dict[str, Any]],
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


_FONT = "Inter, ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif"

_SEVERITY_COLORS: dict[str, str] = {
    "CRITICAL": "#ff5a5f",
    "HIGH": "#f97316",
    "MEDIUM": "#f0b429",
    "LOW": "#31c6f7",
    "INFO": "#9aa4b2",
}


def _render_svg(data: LaunchCardData) -> str:
    gc = data.verdict_color  # glow color tied to verdict state
    project_lines = _wrap(data.project, 44, 2)
    top_lines = _wrap(data.top_issue_title, 30, 3)
    severity, sev_color = _parse_severity(data.top_issue_meta)
    location = _parse_location(data.top_issue_meta)
    sev_w = max(len(severity) * 8 + 22, 48)

    parts: list[str] = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630"'
        ' viewBox="0 0 1200 630" role="img" aria-label="Swain launch card">',
        "<defs>",
        # Top gradient bar
        '<linearGradient id="bar" x1="0" x2="1" y1="0" y2="0">',
        '  <stop offset="0" stop-color="#2fdd92"/>',
        '  <stop offset="0.5" stop-color="#31c6f7"/>',
        '  <stop offset="1" stop-color="#f0b429"/>',
        "</linearGradient>",
        # Radial verdict-color wash fills left side
        '<radialGradient id="vg" cx="0" cy="0.52" r="0.7"'
        ' gradientUnits="objectBoundingBox">',
        f'  <stop offset="0" stop-color="{gc}" stop-opacity="0.11"/>',
        '  <stop offset="1" stop-color="#0a0c0f" stop-opacity="0"/>',
        "</radialGradient>",
        # Text-glow filter for verdict word
        '<filter id="glow" x="-40%" y="-40%" width="180%" height="180%">',
        '  <feGaussianBlur in="SourceAlpha" stdDeviation="10" result="b"/>',
        f'  <feFlood flood-color="{gc}" flood-opacity="0.5" result="c"/>',
        '  <feComposite in="c" in2="b" operator="in" result="g"/>',
        '  <feMerge><feMergeNode in="g"/><feMergeNode in="SourceGraphic"/></feMerge>',
        "</filter>",
        "</defs>",

        # — Background —
        '<rect width="1200" height="630" fill="#0a0c0f"/>',
        '<rect width="1200" height="630" fill="url(#vg)"/>',
        # Top accent bar
        '<rect x="0" y="0" width="1200" height="4" fill="url(#bar)"/>',
        # Column separator
        '<rect x="676" y="28" width="1" height="546" fill="#141c24"/>',

        # — Header —
        _t("SWAIN", 60, 50, 11, "#2fdd92", weight=800, spacing="3"),
        _t(data.repo_name, 60, 74, 15, "#3d4f5d"),
        _t(data.stack, 1140, 50, 13, "#3d4f5d", anchor="end"),

        # — Left: Verdict —
        _tg(data.verdict, 60, 222, 100, data.verdict_color, weight=900),
        _t(data.verdict_summary, 60, 268, 21, "#b8c8d4", weight=500),
        # Project description
        *[
            _t(line, 60, 318 + i * 27, 17, "#4e6070")
            for i, line in enumerate(project_lines)
        ],
        # Stack / surfaces footer line
        _t(f"{data.surfaces}", 60, 410, 13, "#334455"),

        # — Right: Metric cards —
        *_metric_card(
            700,
            38,
            "open findings",
            str(data.open_findings),
            "#31c6f7",
            205,
        ),
        *_metric_card(935, 38, "launch blockers", str(data.launch_blockers), gc, 205),

        # — Right: Top-finding card —
        *_finding_card(
            700,
            232,
            440,
            top_lines,
            severity,
            sev_color,
            sev_w,
            data.top_issue_id,
            location,
            gc,
        ),

        # — Footer —
        '<rect x="0" y="572" width="1200" height="58" fill="#060809"/>',
        '<rect x="0" y="572" width="1200" height="1" fill="#141c24"/>',
        _t("AI security for vibe coders", 60, 608, 13, "#2fdd92", weight=600),
        _t("·", 256, 608, 13, "#253040"),
        _t("swain.sh", 272, 608, 13, "#3d4f5d"),
        _t(data.generated_at, 1140, 608, 12, "#3d4f5d", anchor="end"),

        "</svg>",
        "",
    ]
    return "\n".join(parts)


def _t(
    text: str,
    x: int,
    y: int,
    size: int,
    color: str,
    *,
    weight: int = 400,
    anchor: str = "start",
    spacing: str = "0",
) -> str:
    attrs = (
        f'x="{x}" y="{y}" fill="{color}" font-family="{_FONT}"'
        f' font-size="{size}" font-weight="{weight}"'
    )
    if anchor != "start":
        attrs += f' text-anchor="{anchor}"'
    if spacing != "0":
        attrs += f' letter-spacing="{spacing}"'
    return f"<text {attrs}>{html.escape(str(text))}</text>"


def _tg(
    text: str,
    x: int,
    y: int,
    size: int,
    color: str,
    *,
    weight: int = 900,
) -> str:
    """Text with glow filter applied."""
    return (
        f'<text x="{x}" y="{y}" fill="{color}" font-family="{_FONT}"'
        f' font-size="{size}" font-weight="{weight}" filter="url(#glow)">'
        f"{html.escape(str(text))}</text>"
    )


def _metric_card(
    x: int,
    y: int,
    label: str,
    value: str,
    color: str,
    width: int,
) -> list[str]:
    mid = x + width // 2
    return [
        f'<rect x="{x}" y="{y}" width="{width}" height="170" rx="14"'
        ' fill="#0c1018" stroke="#1c2636"/>',
        _t(value, mid, y + 108, 66, color, weight=800, anchor="middle"),
        _t(label, mid, y + 144, 13, "#4a6070", anchor="middle"),
    ]


def _finding_card(
    x: int,
    y: int,
    width: int,
    title_lines: list[str],
    severity: str,
    sev_color: str,
    sev_w: int,
    finding_id: str,
    location: str,
    verdict_color: str,
) -> list[str]:
    if not finding_id:
        return _clean_scan_card(x, y, width, verdict_color)

    parts: list[str] = [
        f'<rect x="{x}" y="{y}" width="{width}" height="308" rx="14"'
        ' fill="#0c1018" stroke="#1c2636"/>',
        # "Fix first" label + finding id
        _t("Fix first", x + 20, y + 36, 12, "#3d4f5d", weight=600, spacing="0.5"),
        _t(f"#{finding_id}", x + width - 20, y + 36, 12, "#3d4f5d", anchor="end"),
        # Severity badge pill
        f'<rect x="{x + 20}" y="{y + 50}" width="{sev_w}" height="24" rx="6"'
        f' fill="{sev_color}22"/>',
        _t(severity, x + 20 + sev_w // 2, y + 66, 11, sev_color,
           weight=700, anchor="middle"),
    ]
    # Title lines
    for i, line in enumerate(title_lines[:3]):
        parts.append(_t(line, x + 20, y + 116 + i * 28, 19, "#dde6ee", weight=500))
    # Location
    if location:
        parts.append(_t(location, x + 20, y + 116 + len(title_lines[:3]) * 28 + 20,
                        12, "#3d4f5d"))
    return parts


def _clean_scan_card(
    x: int,
    y: int,
    width: int,
    color: str,
) -> list[str]:
    return [
        f'<rect x="{x}" y="{y}" width="{width}" height="308" rx="14"'
        f' fill="#0c1018" stroke="{color}44"/>',
        _t("No open findings", x + width // 2, y + 130, 20, color,
           weight=600, anchor="middle"),
        _t("Ready to ship.", x + width // 2, y + 162, 15, "#3d4f5d", anchor="middle"),
    ]


def _parse_severity(meta: str) -> tuple[str, str]:
    for sev, col in _SEVERITY_COLORS.items():
        if meta.upper().startswith(sev):
            return sev, col
    return "", "#9aa4b2"


def _parse_location(meta: str) -> str:
    parts = meta.split(" - ")
    return parts[-1].strip() if len(parts) >= 3 else ""


def _wrap(text: str, width: int, max_lines: int) -> list[str]:
    lines = textwrap.wrap(_clean(text), width=width) or [""]
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip(".") + "..."
    return lines


def _clean(text: str) -> str:
    return " ".join(str(text).replace("\n", " ").split())
