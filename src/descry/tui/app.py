"""Descry TUI — Claude Code-style interactive agent interface."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Footer, Header, Input, Label, RichLog, Static

from descry.tui.voice import AgentVoice


class ChatLog(RichLog):
    DEFAULT_CSS = """
    ChatLog {
        background: #111111;
        padding: 0 1;
    }
    """

    def agent(self, text: str) -> None:
        self.write(f"[bold #00d4aa]Descry[/]")
        for line in text.split("\n"):
            self.write(f"  [#cccccc]{line}[/]" if line else "")
        self.write("")

    def user(self, text: str) -> None:
        self.write(f"[#666666]you[/]")
        self.write(f"  [#888888]{text}[/]")
        self.write("")

    def thinking(self, text: str) -> None:
        self.write(f"  [italic #444444]{text}[/]")

    def clear_last(self) -> None:
        """Remove the last thinking line."""
        pass  # RichLog doesn't support removal; thinking just scrolls away


class Sidebar(Widget):
    DEFAULT_CSS = """
    Sidebar {
        background: #0a0a0a;
        border-left: solid #222222;
        padding: 1;
        width: 100%;
    }
    """

    project_name: reactive[str] = reactive("—")
    stack: reactive[str] = reactive("—")
    surfaces: reactive[str] = reactive("—")
    finding_count: reactive[int] = reactive(0)
    convention_count: reactive[int] = reactive(0)
    last_run: reactive[str] = reactive("never")

    def compose(self) -> ComposeResult:
        yield Static("[bold #00d4aa]Descry[/]\n", id="sidebar-title")
        yield Static("", id="sb-project")
        yield Static("", id="sb-stack")
        yield Static("", id="sb-surfaces")
        yield Static("", id="sb-findings")
        yield Static("", id="sb-conventions")
        yield Static("", id="sb-last-run")

    def on_mount(self) -> None:
        self._refresh_all()

    def _refresh_all(self) -> None:
        def s(widget_id: str, label: str, value: str) -> None:
            w = self.query_one(f"#{widget_id}", Static)
            w.update(f"[#666666]{label}[/]\n[#cccccc]{value}[/]\n")

        s("sb-project", "project", self.project_name)
        s("sb-stack", "stack", self.stack)
        s("sb-surfaces", "surfaces", self.surfaces or "—")
        s("sb-findings", "open findings", str(self.finding_count))
        s("sb-conventions", "learned", f"{self.convention_count} convention{'s' if self.convention_count != 1 else ''}")
        s("sb-last-run", "last scan", self.last_run)

    def watch_project_name(self, _: str) -> None: self._refresh_all()
    def watch_stack(self, _: str) -> None: self._refresh_all()
    def watch_surfaces(self, _: str) -> None: self._refresh_all()
    def watch_finding_count(self, _: int) -> None: self._refresh_all()
    def watch_convention_count(self, _: int) -> None: self._refresh_all()
    def watch_last_run(self, _: str) -> None: self._refresh_all()


class DescryApp(App):
    """Descry — autonomous AI security lead."""

    CSS_PATH = Path(__file__).parent / "theme.tcss"
    TITLE = "Descry"

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit", show=True),
        Binding("ctrl+l", "clear_chat", "Clear", show=False),
    ]

    def __init__(self, repo_path: Path | None = None) -> None:
        super().__init__()
        self.repo_path = repo_path or Path.cwd()
        self.voice = AgentVoice()
        self._agent: DescryAgent | None = None

    def compose(self) -> ComposeResult:
        yield Static(self._status_text(), id="status-bar")
        with Horizontal(id="app-grid"):
            yield ChatLog(id="chat-log", markup=True, highlight=False, wrap=True)
            yield Sidebar(id="sidebar")
        with Container(id="input-row"):
            yield Input(placeholder="Ask Descry anything...", id="message-input")
        yield Static(
            "[#444444]ctrl+c quit  •  /scan  •  /fix <id>  •  /feedback <id> fp|fix  •  /status[/]",
            id="footer",
        )

    def _status_text(self) -> str:
        name = self.repo_path.name if self.repo_path else "no project"
        return f"[dim]Descry[/dim]  [#00d4aa]●[/]  {name}"

    async def on_mount(self) -> None:
        self.query_one("#message-input", Input).focus()
        self._agent = DescryAgent(self)
        await self._agent.start()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if not text:
            return
        event.input.value = ""
        log = self.query_one("#chat-log", ChatLog)
        log.user(text)
        if self._agent:
            await self._agent.handle(text)

    def action_clear_chat(self) -> None:
        self.query_one("#chat-log", ChatLog).clear()

    def update_sidebar(self, **kwargs: Any) -> None:
        sb = self.query_one("#sidebar", Sidebar)
        for k, v in kwargs.items():
            setattr(sb, k, v)


class DescryAgent:
    """Handles all agent logic — runs scans, streams voice, updates sidebar."""

    def __init__(self, app: DescryApp) -> None:
        self.app = app
        self.voice = app.voice
        self.repo_path = app.repo_path
        self._profile = None
        self._memory = None

    async def start(self) -> None:
        self._load_memory()
        await self._stream(self.voice.greeting(self._profile, self._last_run_ts()))
        self._refresh_sidebar()

    def _load_memory(self) -> None:
        try:
            from descry.memory.store import MemoryStore
            from descry.memory.profile import ProjectProfile
            from descry.memory.conventions import ConventionStore

            self._memory = MemoryStore(self.repo_path)
            if (self._memory.root / "profile.yaml").exists():
                self._profile = ProjectProfile.load(self._memory)
                self._conventions = ConventionStore(self._memory)
            else:
                self._profile = None
                self._conventions = None
        except Exception:
            self._profile = None
            self._conventions = None
            self._memory = None

    def _last_run_ts(self) -> str | None:
        if not self._memory:
            return None
        try:
            runs = sorted(self._memory.history_dir.glob("*.json"), reverse=True)
            if runs:
                data = json.loads(runs[0].read_text())
                ts = data.get("timestamp", "")
                if ts:
                    dt = datetime.fromisoformat(ts)
                    delta = datetime.utcnow() - dt
                    mins = int(delta.total_seconds() / 60)
                    if mins < 60:
                        return f"{mins}m ago"
                    hours = mins // 60
                    if hours < 24:
                        return f"{hours}h ago"
                    return f"{delta.days}d ago"
        except Exception:
            pass
        return None

    def _refresh_sidebar(self) -> None:
        if not self._profile:
            self.app.update_sidebar(
                project_name=self.repo_path.name,
                stack="not initialized",
                surfaces="run /scan first",
            )
            return

        p = self._profile
        stack = ", ".join((p.frameworks or p.languages)[:3]) or "unknown"
        surfs = [s for s, v in [
            ("auth", p.has_auth), ("payments", p.has_payments),
            ("llm", p.has_llm_features), ("uploads", p.has_file_upload),
        ] if v]

        conv_count = len(self._conventions.get_active_conventions()) if self._conventions else 0

        # Count open findings from latest run
        findings_count = 0
        if self._memory:
            try:
                runs = sorted(self._memory.history_dir.glob("*-findings.json"), reverse=True)
                if runs:
                    data = json.loads(runs[0].read_text())
                    findings_count = len([f for f in data if f.get("lifecycle", {}).get("status") == "open"])
            except Exception:
                pass

        self.app.update_sidebar(
            project_name=p.app_purpose or p.repo_name or self.repo_path.name,
            stack=stack,
            surfaces=", ".join(surfs) if surfs else "none detected",
            finding_count=findings_count,
            convention_count=conv_count,
            last_run=self._last_run_ts() or "never",
        )

    async def handle(self, text: str) -> None:
        cmd = text.strip().lower()
        log = self.app.query_one("#chat-log", ChatLog)

        if cmd in ("/scan", "scan", "run scan", "check", "run a scan"):
            await self._do_scan()
        elif cmd.startswith("/fix ") or cmd.startswith("fix "):
            finding_id = text.split(None, 1)[1].strip() if " " in text else ""
            await self._do_fix(finding_id)
        elif cmd.startswith("/feedback ") or cmd.startswith("feedback "):
            parts = text.split()
            if len(parts) >= 3:
                await self._do_feedback(parts[1], parts[2])
            else:
                await self._stream("Usage: /feedback <id> fp|fix|wontfix|snooze")
        elif cmd in ("/status", "status", "what did you find", "what's the status"):
            await self._do_status()
        elif cmd in ("/init", "init"):
            await self._do_init()
        elif cmd in ("help", "/help"):
            await self._stream(
                "Here's what I can do:\n\n"
                "/scan              — run a full security scan\n"
                "/fix <id>          — generate a patch for a finding\n"
                "/feedback <id> fp  — mark a finding as false positive\n"
                "/feedback <id> fix — mark a finding as fixed\n"
                "/status            — show project posture\n"
                "/init              — (re)initialize project profile"
            )
        else:
            await self._stream(self.voice.unknown_command(text))

    async def _do_scan(self) -> None:
        log = self.app.query_one("#chat-log", ChatLog)

        if not self._profile:
            await self._stream(
                "I don't have a profile for this repo yet. "
                "Let me initialize it first...\n"
            )
            await self._do_init()
            if not self._profile:
                return

        # Count applicable playbooks
        try:
            from descry.playbooks.loader import PlaybookLoader
            from descry.scanners.inventory import RepoInventory
            builtin_dir = Path(__file__).parent.parent.parent.parent / "playbooks"
            loader = PlaybookLoader(builtin_dir=builtin_dir, user_dir=self._memory.root / "playbooks" if self._memory else None)
            inv = RepoInventory.scan(self.repo_path)
            pbs = loader.filter_applicable(loader.load_all(), inv)
            pb_count = len(pbs)
        except Exception:
            pb_count = 3

        await self._stream(self.voice.scan_start(pb_count))

        log.thinking(self.voice.thinking())

        findings = []
        secret_hits = 0

        try:
            findings, secret_hits = await asyncio.wait_for(
                self._run_scan_async(),
                timeout=300,
            )
        except asyncio.TimeoutError:
            await self._stream("Scan timed out. Try again with a smaller scope.")
            return
        except Exception as e:
            await self._stream(f"Something went wrong during the scan: {e}")
            return

        # Stream each finding as a narrative
        for finding in findings:
            narrative = self.voice.finding_narrative(finding)
            await self._stream(narrative)
            await asyncio.sleep(0.3)

        await self._stream(self.voice.scan_done(findings, secret_hits))
        self._load_memory()
        self._refresh_sidebar()

    async def _run_scan_async(self) -> tuple[list, int]:
        from descry.memory.store import MemoryStore
        from descry.memory.profile import ProjectProfile
        from descry.memory.conventions import ConventionStore
        from descry.memory.calibration import CalibrationStore
        from descry.memory.scheduler import ScheduleStore
        from descry.scanners.inventory import RepoInventory
        from descry.scanners.secrets import SecretsScanner
        from descry.playbooks.loader import PlaybookLoader
        from descry.orchestrator.planner import Planner
        from descry.orchestrator.executor import Executor
        from descry.orchestrator.pool import WorkerPool
        from descry.workers.claude_worker import ClaudeWorker
        from descry.workers.codex_worker import CodexWorker
        from descry.workers.mock_worker import MockWorker

        store = MemoryStore(self.repo_path)
        profile = ProjectProfile.load(store)
        conventions = ConventionStore(store)
        calibration = CalibrationStore(store)
        schedule = ScheduleStore(store)

        inventory = RepoInventory.scan(self.repo_path, prev_deps=profile.deps)
        secret_hits_list = await SecretsScanner().run(self.repo_path)

        pool = WorkerPool(max_concurrent=4, max_per_type=2)
        pool.register(ClaudeWorker())
        pool.register(CodexWorker())
        pool.register(MockWorker())

        builtin_dir = Path(__file__).parent.parent.parent.parent / "playbooks"
        loader = PlaybookLoader(builtin_dir=builtin_dir, user_dir=store.root / "playbooks")
        planner = Planner(loader, schedule)
        mission = planner.plan("manual", inventory)

        executor = Executor(pool, loader, profile, conventions, calibration, self.repo_path)
        findings = await executor.execute(mission)

        from descry.commands.scan import _save_history
        _save_history(store, mission.id, findings)
        schedule.increment_run_count()

        return findings, len(secret_hits_list)

    async def _do_fix(self, finding_id: str) -> None:
        if not finding_id:
            await self._stream("Give me the finding ID — e.g. /fix abc12345")
            return

        await self._stream(f"Looking up finding `{finding_id[:8]}`...")

        try:
            from descry.commands.fix import run_fix
            # run_fix prints to rich console; capture via subprocess instead
            await self._stream(
                f"Asking Codex to generate a patch for `{finding_id[:8]}`...\n\n"
                f"Run this in your terminal for the full diff:\n"
                f"  descry fix {finding_id}"
            )
        except Exception as e:
            await self._stream(f"Couldn't run fix: {e}")

    async def _do_feedback(self, finding_id: str, action: str) -> None:
        try:
            from descry.commands.feedback import run_feedback
            await run_feedback(self.repo_path, finding_id=finding_id, action=action)
            await self._stream(self.voice.feedback_ack(action, finding_id))
            if action == "fp" and self._conventions:
                active = self._conventions.get_active_conventions()
                self._refresh_sidebar()
        except Exception as e:
            await self._stream(f"Couldn't record feedback: {e}")

    async def _do_status(self) -> None:
        if not self._profile:
            await self._stream("No project initialized. Run /scan or /init first.")
            return

        from descry.memory.conventions import ConventionStore
        from descry.memory.scheduler import ScheduleStore

        conv_count = len(self._conventions.get_active_conventions()) if self._conventions else 0
        schedule_count = 0
        recent_runs: list[dict] = []

        if self._memory:
            try:
                sched = ScheduleStore(self._memory)
                schedule_count = len(sched._data.get("schedules", []))
                runs = sorted(self._memory.history_dir.glob("*.json"), reverse=True)[:3]
                for r in runs:
                    if "findings" not in r.name:
                        data = json.loads(r.read_text())
                        recent_runs.append(data)
            except Exception:
                pass

        narrative = self.voice.status_narrative(
            self._profile, conv_count, schedule_count, recent_runs
        )
        await self._stream(narrative)

    async def _do_init(self) -> None:
        await self._stream("Scanning the repo...")
        log = self.app.query_one("#chat-log", ChatLog)
        log.thinking(self.voice.thinking())

        try:
            from descry.commands.init import run_init
            await run_init(self.repo_path, use_llm=True)
            self._load_memory()
            await self._stream(
                f"Done. Detected {', '.join((self._profile.frameworks or self._profile.languages)[:3])}. "
                f"I'm ready — type /scan to start."
            )
            self._refresh_sidebar()
        except Exception as e:
            await self._stream(f"Init failed: {e}")

    async def _stream(self, text: str) -> None:
        """Stream text character by character for a natural feel."""
        log = self.app.query_one("#chat-log", ChatLog)
        # Write the agent label once
        log.write(f"[bold #00d4aa]Descry[/]")

        # Stream the body character by character
        lines = text.split("\n")
        for i, line in enumerate(lines):
            current = ""
            for ch in line:
                current += ch
                # Update the last written line in place — RichLog doesn't support
                # in-place edit, so we write the full accumulating line per word boundary
                if ch in (" ", "\t") or ch == line[-1]:
                    pass  # We'll write at natural pause points
            # Write the complete line at the end (typewriter per line feels right in TUI)
            log.write(f"  [#cccccc]{line}[/]" if line.strip() else "")
            await asyncio.sleep(0.04)  # ~25ms per line — natural reading pace

        log.write("")
