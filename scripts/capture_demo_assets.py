#!/usr/bin/env python3
"""Capture repeatable public demo assets for release docs."""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
DEMO_REPO = ROOT / "examples" / "launchpad-saas"
DEFAULT_OUT_DIR = ROOT / "docs" / "assets" / "demo"
REPORTS_DIR = ROOT / "tests" / "fixtures" / "worker_reports" / "launch-risk-saas"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


@dataclass(frozen=True)
class CapturedCommand:
    name: str
    title: str
    command: list[str]
    output: str


def main() -> None:
    args = _parse_args()
    out_dir = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    swain = _resolve_swain(args.swain_bin)
    _clean_demo_local_state()
    try:
        commands = []
        commands.append(
            _capture_command(
                name="doctor",
                title="Swain Doctor",
                command=[
                    str(swain),
                    "doctor",
                    "examples/launchpad-saas",
                    "--no-probe-workers",
                ],
            )
        )
        _seed_demo_history()
        commands.append(
            _capture_command(
                name="status",
                title="Project Status",
                command=[str(swain), "status", "examples/launchpad-saas"],
            )
        )
        _write_launch_card_asset(out_dir / "launch-card.svg")
        commands.append(
            _capture_command(
                name="scan-mock",
                title="Mock Scan",
                command=[
                    str(swain),
                    "scan",
                    "examples/launchpad-saas",
                    "--output",
                    "markdown",
                    "--mock",
                ],
            )
        )
    finally:
        _clean_demo_local_state()

    for captured in commands:
        _write_terminal_svg(captured, out_dir / f"{captured.name}.svg")

    _write_tui_transcript_svg(out_dir / "tui-first-run.svg")
    _write_finding_svg(out_dir / "finding-narrative.svg")
    _write_scan_flow_gif(out_dir / "scan-flow.gif")
    _write_transcript(commands, out_dir / "transcript.md")

    print(f"Wrote demo assets to {out_dir}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUT_DIR,
        help="Directory for generated SVG and transcript assets.",
    )
    parser.add_argument(
        "--swain-bin",
        default=None,
        help="Path to the swain executable. Defaults to .venv/bin/swain.",
    )
    return parser.parse_args()


def _resolve_swain(value: str | None) -> Path:
    if value:
        candidate = Path(value)
    else:
        candidate = ROOT / ".venv" / "bin" / "swain"
        if not candidate.exists():
            found = shutil.which("swain")
            if found:
                candidate = Path(found)
    if not candidate.exists():
        raise SystemExit(
            "Could not find swain. Pass --swain-bin or create .venv/bin/swain."
        )
    return candidate.resolve()


def _capture_command(
    *,
    name: str,
    title: str,
    command: list[str],
    timeout_s: int = 180,
) -> CapturedCommand:
    proc = subprocess.run(  # noqa: S603
        command,
        cwd=ROOT,
        env={**os.environ, "COLUMNS": "160"},
        capture_output=True,
        text=True,
        timeout=timeout_s,
        check=False,
    )
    output = _sanitize_output((proc.stdout + proc.stderr).strip())
    if proc.returncode != 0:
        raise SystemExit(
            f"{name} failed with exit code {proc.returncode}\n{output}"
        )
    return CapturedCommand(
        name=name,
        title=title,
        command=command,
        output=output,
    )


def _write_terminal_svg(captured: CapturedCommand, path: Path) -> None:
    console = _asset_console(captured.title)
    command_text = " ".join(_display_command(captured.command))
    console.print(
        Panel(
            Text(command_text, style="bold cyan"),
            title="command",
            border_style="cyan",
            box=box.ROUNDED,
        )
    )
    console.print(
        Panel(
            Text(captured.output or "(no output)"),
            title=captured.title,
            border_style="green",
            box=box.ROUNDED,
        )
    )
    console.save_svg(str(path), title=f"Swain - {captured.title}")


def _write_tui_transcript_svg(path: Path) -> None:
    console = _asset_console("Swain TUI")
    messages = [
        (
            "Swain",
            (
                "I'm looking at your react, fastapi, stripe project. "
                "I see auth, payments, uploads in the mix.\n\n"
                "Hey. First time with this repo. Run /scan and I'll check "
                "the risky surfaces first."
            ),
        ),
        ("you", "are we ready to ship?"),
        (
            "Swain",
            (
                "Before shipping, I want a clean pass on auth, payments, "
                "uploads, secrets, and tenant/data access. Run /scan, then "
                "fix anything critical or high before you trust the launch."
            ),
        ),
    ]
    for speaker, text in messages:
        style = "bold green" if speaker == "Swain" else "bold white"
        console.print(
            Panel(
                Text(text),
                title=speaker,
                title_align="left",
                border_style=style,
                box=box.ROUNDED,
            )
        )
    console.save_svg(str(path), title="Swain - TUI first run")


def _write_scan_flow_gif(path: Path) -> None:
    convert = shutil.which("convert")
    if not convert:
        raise SystemExit(
            "ImageMagick `convert` is required to generate scan-flow.gif."
        )

    frames = [
        [
            (
                "Swain",
                (
                    "I'm looking at your react, fastapi, stripe project. "
                    "I see auth, payments, uploads in the mix.\n\n"
                    "Hey. First time with this repo. Run /scan and I'll "
                    "check the risky surfaces first."
                ),
            ),
            ("you", "are we ready to ship?"),
        ],
        [
            (
                "Swain",
                (
                    "Before shipping, I want a clean pass on auth, payments, "
                    "uploads, secrets, and tenant/data access. Run /scan, "
                    "then fix anything critical or high before you trust the "
                    "launch."
                ),
            ),
            ("you", "/scan"),
        ],
        [
            ("Swain", "On it. 7 checks queued."),
            ("system", "Running deterministic scanners...\n7 playbooks to run"),
            (
                "Swain",
                (
                    "I found a critical billing trust bug. The checkout route "
                    "accepts client-supplied price and tenant metadata."
                ),
            ),
        ],
        [
            (
                "Swain",
                (
                    "This one's bad.\n\n"
                    "Checkout trusts client-supplied price and tenant metadata "
                    "— in `backend/app/api/v1/billing.py` line 15.\n"
                    "ID: `bee77255`.\n\n"
                    "Fix: map plans to server-owned Stripe price IDs and "
                    "derive tenant_id from the authenticated user."
                ),
            ),
            (
                "Swain",
                "I'd start with `bee77255`. Everything else can wait.",
            ),
        ],
    ]

    with tempfile.TemporaryDirectory(prefix="swain-gif-") as tmp:
        frame_paths = []
        for index, messages in enumerate(frames):
            frame_path = Path(tmp) / f"frame-{index:02d}.svg"
            _write_flow_frame(messages, frame_path)
            frame_paths.append(frame_path)

        proc = subprocess.run(  # noqa: S603
            [
                convert,
                "-background",
                "#111111",
                "-density",
                "144",
                "-delay",
                "130",
                "-loop",
                "0",
                *[str(frame) for frame in frame_paths],
                str(path),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
    if proc.returncode != 0:
        raise SystemExit(
            "Could not generate scan-flow.gif with ImageMagick:\n"
            f"{proc.stderr.strip()}"
        )


def _write_flow_frame(messages: list[tuple[str, str]], path: Path) -> None:
    console = _asset_console("Scan Flow")
    for speaker, text in messages:
        if speaker == "Swain":
            border_style = "green"
        elif speaker == "system":
            border_style = "cyan"
        else:
            border_style = "white"
        console.print(
            Panel(
                Text(text),
                title=speaker,
                title_align="left",
                border_style=border_style,
                box=box.ROUNDED,
            )
        )
    console.save_svg(str(path), title="Swain - scan flow")


def _write_finding_svg(path: Path) -> None:
    from descry.models import Finding, FindingSource, WorkerType

    raw = json.loads((REPORTS_DIR / "sast.payments.json").read_text())
    finding_data = raw["findings"][0]
    finding_data["source"] = FindingSource(
        worker=WorkerType.CLAUDE,
        playbook="sast.payments",
        playbook_version=1,
        run_id="demo",
    ).model_dump(mode="json")
    finding = Finding.model_validate(finding_data)
    line = finding.evidence.line_start
    loc = f"`{finding.evidence.file}`" + (f" line {line}" if line else "")
    narrative = "\n".join([
        "This one's bad.",
        "",
        f"{finding.title} — in {loc}.",
        f"ID: `{finding.id[:8]}`.",
        finding.description,
        finding.exploitability.assessment,
        f"Fix: {finding.remediation.summary}",
    ])

    console = _asset_console("Finding Narrative")
    console.print(
        Panel(
            Text(narrative),
            title="Swain",
            title_align="left",
            border_style="red",
            box=box.ROUNDED,
        )
    )
    console.save_svg(str(path), title="Swain - finding narrative")


def _write_launch_card_asset(path: Path) -> None:
    from descry.commands.launch_card import (
        build_launch_card_data,
        write_launch_card_svg,
    )

    data = build_launch_card_data(
        DEMO_REPO,
        generated_at=datetime(2026, 5, 29, 16, 45, tzinfo=UTC),
    )
    write_launch_card_svg(data, path)
    _write_png_from_svg(path, path.with_suffix(".png"))


def _write_png_from_svg(svg_path: Path, png_path: Path) -> None:
    convert = shutil.which("convert")
    if not convert:
        raise SystemExit(
            "ImageMagick `convert` is required to generate launch-card.png."
        )
    proc = subprocess.run(  # noqa: S603
        [convert, str(svg_path), str(png_path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    if proc.returncode != 0:
        raise SystemExit(
            "Could not generate launch-card.png with ImageMagick:\n"
            f"{proc.stderr.strip()}"
        )


def _seed_demo_history() -> None:
    from descry.models import Finding, FindingSource, Severity, WorkerType

    run_id = "demo12345678"
    timestamp = datetime(2026, 5, 29, 16, 45, tzinfo=UTC)
    report_files = [
        "sast.payments.json",
        "sast.file-upload.json",
        "sast.sql-injection.json",
        "sast.xss.react.json",
    ]
    findings = []
    for report_file in report_files:
        raw = json.loads((REPORTS_DIR / report_file).read_text())
        playbook = report_file.removesuffix(".json")
        for item in raw.get("findings", []):
            finding_data = dict(item)
            finding_data["source"] = FindingSource(
                worker=WorkerType.CLAUDE,
                playbook=playbook,
                playbook_version=1,
                run_id=run_id,
            ).model_dump(mode="json")
            finding = Finding.model_validate(finding_data)
            finding.source.run_id = run_id
            finding.lifecycle.first_seen = timestamp
            finding.lifecycle.last_seen = timestamp
            findings.append(finding)

    history_dir = DEMO_REPO / ".swain" / "demo-history"
    history_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "run_id": run_id,
        "timestamp": timestamp.isoformat(),
        "finding_count": len(findings),
        "severities": {
            severity.value: sum(
                1 for finding in findings if finding.severity == severity
            )
            for severity in Severity
        },
    }
    (history_dir / f"20260529-164500-{run_id}.json").write_text(
        json.dumps(summary, indent=2)
    )
    (history_dir / f"{run_id}-findings.json").write_text(
        json.dumps(
            [finding.model_dump(mode="json") for finding in findings],
            indent=2,
        )
    )


def _write_transcript(commands: list[CapturedCommand], path: Path) -> None:
    lines = [
        "# Demo Asset Transcript",
        "",
        "Generated from `examples/launchpad-saas` using "
        "`scripts/capture_demo_assets.py`.",
        "The status screenshot is seeded from checked-in fixture findings so "
        "the fix-first handoff is reproducible without live Claude/Codex quota.",
        "The launch card is a 1200x630 share image generated from the same "
        "fix-first history.",
        "",
        "## Launch Card",
        "",
        "```bash",
        "swain launch-card examples/launchpad-saas "
        "--out docs/assets/demo/launch-card.svg",
        "```",
        "",
    ]
    for captured in commands:
        lines.extend([
            f"## {captured.title}",
            "",
            "```bash",
            " ".join(_display_command(captured.command)),
            "```",
            "",
            "```text",
            captured.output,
            "```",
            "",
        ])
    path.write_text("\n".join(lines))


def _asset_console(title: str) -> Console:
    console = Console(
        color_system="truecolor",
        file=io.StringIO(),
        force_terminal=True,
        record=True,
        width=108,
    )
    console.print(Text(f"Swain / {title}", style="bold #00d4aa"))
    console.print()
    return console


def _display_command(command: list[str]) -> list[str]:
    display = []
    for part in command:
        try:
            path = Path(part)
            if path == (ROOT / ".venv" / "bin" / "swain").resolve():
                display.append("swain")
                continue
        except OSError:
            pass
        display.append(part)
    return display


def _sanitize_output(output: str) -> str:
    output = output.replace(str(ROOT), "<swain>")
    output = output.replace(str(Path.home()), "~")
    try:
        repo_from_home = f"~/{ROOT.relative_to(Path.home())}"
    except ValueError:
        repo_from_home = ""
    if repo_from_home:
        output = output.replace(repo_from_home, "<swain>")
    output = re.sub(r"Mission [0-9a-f]{12}", "Mission demo12345678", output)
    output = re.sub(
        r"\*\*Run ID\*\*: `[0-9a-f]+`",
        "**Run ID**: `demo12345678`",
        output,
    )
    output = re.sub(
        r"\*\*Date\*\*: .+ UTC",
        "**Date**: 2026-05-29 16:45 UTC",
        output,
    )
    return output


def _clean_demo_local_state() -> None:
    shutil.rmtree(DEMO_REPO / ".swain" / ".local", ignore_errors=True)


if __name__ == "__main__":
    main()
