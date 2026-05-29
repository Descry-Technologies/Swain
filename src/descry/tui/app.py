"""
Descry TUI — interactive agent interface.

The agent feels human because:
1. Characters stream with variable timing (punctuation pauses, sentence pauses)
2. Natural language is interpreted by claude, not regex-matched
3. The agent references earlier parts of the session
4. It has opinions, not just data
"""

from __future__ import annotations

import asyncio
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Input, RichLog, Static

from descry.tui.voice import AgentVoice


# ── Typewriter timing ────────────────────────────────────────────────────────

_CHAR_DELAY   = 0.018   # base per-character delay (s)
_WORD_DELAY   = 0.04    # extra pause at word boundaries
_COMMA_DELAY  = 0.12    # pause after comma
_PERIOD_DELAY = 0.22    # pause after sentence-ending punctuation
_NEWLINE_DELAY = 0.15   # pause between lines


async def _typewrite(log: "ChatLog", text: str) -> None:
    """Stream text with human-like variable timing."""
    lines = text.split("\n")
    for li, line in enumerate(lines):
        if not line.strip():
            log.write("")
            await asyncio.sleep(_NEWLINE_DELAY)
            continue

        # Accumulate the line char by char, writing in-place via a mutable buffer
        # RichLog doesn't support in-place edit, so we write word-by-word instead
        words = line.split(" ")
        rendered = ""
        for wi, word in enumerate(words):
            rendered += ("" if wi == 0 else " ") + word
            await asyncio.sleep(_WORD_DELAY)

            # Extra pause on punctuation
            if word.endswith((".", "!", "?")):
                await asyncio.sleep(_PERIOD_DELAY)
            elif word.endswith(","):
                await asyncio.sleep(_COMMA_DELAY)

        log.write(f"  [#cccccc]{rendered}[/]" if rendered else "")
        if li < len(lines) - 1:
            await asyncio.sleep(_NEWLINE_DELAY)


# ── Widgets ───────────────────────────────────────────────────────────────────

class ChatLog(RichLog):
    DEFAULT_CSS = """
    ChatLog {
        background: #111111;
        padding: 0 1;
        border: none;
    }
    """

    def agent_label(self) -> None:
        self.write("[bold #00d4aa]Descry[/]")

    def user_label(self, text: str) -> None:
        self.write(f"[#555555]you  [#888888]{text}[/]")
        self.write("")

    def system_line(self, text: str) -> None:
        self.write(f"  [italic #444444]{text}[/]")


class Sidebar(Widget):
    DEFAULT_CSS = """
    Sidebar {
        background: #0a0a0a;
        border-left: solid #1e1e1e;
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
        yield Static("[bold #00d4aa]Descry[/]\n", id="sb-brand")
        yield Static("", id="sb-project")
        yield Static("", id="sb-stack")
        yield Static("", id="sb-surfaces")
        yield Static("", id="sb-findings")
        yield Static("", id="sb-conventions")
        yield Static("", id="sb-last-run")

    def on_mount(self) -> None:
        self._render()

    def _render(self) -> None:
        def row(wid: str, label: str, val: str) -> None:
            self.query_one(f"#{wid}", Static).update(
                f"[#555555]{label}[/]\n[#cccccc]{val or '—'}[/]\n"
            )
        row("sb-project",     "project",    self.project_name)
        row("sb-stack",       "stack",      self.stack)
        row("sb-surfaces",    "surfaces",   self.surfaces)
        row("sb-findings",    "findings",   str(self.finding_count) if self.finding_count else "none open")
        row("sb-conventions", "learned",    f"{self.convention_count} convention{'s' if self.convention_count != 1 else ''}")
        row("sb-last-run",    "last scan",  self.last_run)

    def watch_project_name(self, _: str) -> None: self._render()
    def watch_stack(self, _: str) -> None: self._render()
    def watch_surfaces(self, _: str) -> None: self._render()
    def watch_finding_count(self, _: int) -> None: self._render()
    def watch_convention_count(self, _: int) -> None: self._render()
    def watch_last_run(self, _: str) -> None: self._render()


# ── App ───────────────────────────────────────────────────────────────────────

class DescryApp(App):
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
        yield Static(
            f"[dim]Descry[/]  [#00d4aa]●[/]  {self.repo_path.name}",
            id="status-bar",
        )
        with Horizontal(id="main"):
            yield ChatLog(id="chat-log", markup=True, highlight=False, wrap=True)
            yield Sidebar(id="sidebar")
        yield Input(placeholder="Ask Descry anything...", id="message-input")
        yield Static(
            "[#333333]ctrl+c exit  ·  /scan  ·  /fix <id>  ·  /feedback <id> fp  ·  /status[/]",
            id="footer",
        )

    async def on_mount(self) -> None:
        self.query_one("#message-input", Input).focus()
        self._agent = DescryAgent(self)
        # Run greeting in background so UI renders first
        self.run_worker(self._agent.start(), exclusive=True, name="greeting")

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if not text:
            return
        event.input.value = ""
        log = self.query_one("#chat-log", ChatLog)
        log.user_label(text)
        if self._agent:
            self.run_worker(
                self._agent.handle(text),
                exclusive=False,
                name=f"msg-{id(text)}",
            )

    def action_clear_chat(self) -> None:
        self.query_one("#chat-log", ChatLog).clear()

    def update_sidebar(self, **kwargs: Any) -> None:
        sb = self.query_one("#sidebar", Sidebar)
        for k, v in kwargs.items():
            setattr(sb, k, v)


# ── Agent ─────────────────────────────────────────────────────────────────────

class DescryAgent:
    """
    All agent logic lives here.

    Key design decisions:
    - NLU for ambiguous input goes through claude (if available), not regex
    - Session history is kept so the agent can reference earlier messages
    - Findings are surfaced with opinions, not just listed
    """

    def __init__(self, app: DescryApp) -> None:
        self.app = app
        self.voice = app.voice
        self.repo_path = app.repo_path
        self._profile = None
        self._memory = None
        self._conventions = None
        # Session conversation history for context-aware responses
        self._session: list[dict[str, str]] = []
        self._last_findings: list = []

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        self._load_memory()
        open_findings = self._count_open_findings()
        msg = self.voice.greeting(self._profile, self._last_run_ts(), open_findings)
        await self._stream(msg)
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
        except Exception:
            self._profile = None
            self._conventions = None
            self._memory = None

    # ── Message handling ──────────────────────────────────────────────────────

    async def handle(self, text: str) -> None:
        self._session.append({"role": "user", "content": text})
        cmd = text.strip().lower()

        # Hard commands — no ambiguity
        if cmd in ("/scan", "scan"):
            await self._do_scan()
        elif cmd.startswith(("/fix ", "fix ")):
            fid = text.split(None, 1)[1].strip() if " " in text else ""
            await self._do_fix(fid)
        elif cmd.startswith(("/feedback ", "feedback ")):
            parts = text.split()
            if len(parts) >= 3:
                await self._do_feedback(parts[1], parts[2])
            else:
                await self._say("Try: /feedback <id> fp  or  /feedback <id> fix")
        elif cmd in ("/status", "status"):
            await self._do_status()
        elif cmd in ("/init", "init"):
            await self._do_init()
        elif cmd in ("help", "/help"):
            await self._do_help()
        else:
            # Ambiguous input — use NLU if claude is available, else fallback
            await self._handle_natural(text)

    async def _handle_natural(self, text: str) -> None:
        """Use claude to interpret the intent, then route to the right action."""
        if not shutil.which("claude"):
            await self._say(self.voice.unknown_command(text))
            return

        # Build a short NLU prompt with session context
        history_str = "\n".join(
            f"{m['role']}: {m['content']}" for m in self._session[-6:]
        )
        nlu_prompt = f"""\
You are the intent classifier for a security agent called Descry.
Given the conversation history and the latest user message, classify the intent.

Conversation:
{history_str}

Respond with ONLY one of these JSON objects:
{{"intent": "scan"}}
{{"intent": "status"}}
{{"intent": "fix", "id": "<finding-id-if-mentioned>"}}
{{"intent": "feedback", "id": "<id>", "action": "fp|fix|wontfix|snooze"}}
{{"intent": "explain", "topic": "<what they want explained>"}}
{{"intent": "unknown"}}
"""
        try:
            proc = await asyncio.create_subprocess_exec(
                "claude", "--no-interactive", "--output-format", "text", "-p", nlu_prompt,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=20)
            raw = out.decode(errors="replace").strip()
            # Extract JSON
            s, e = raw.find("{"), raw.rfind("}")
            if s != -1 and e != -1:
                data = json.loads(raw[s:e+1])
                intent = data.get("intent", "unknown")
                if intent == "scan":
                    await self._do_scan()
                    return
                elif intent == "status":
                    await self._do_status()
                    return
                elif intent == "fix":
                    await self._do_fix(data.get("id", ""))
                    return
                elif intent == "feedback":
                    await self._do_feedback(data.get("id", ""), data.get("action", ""))
                    return
                elif intent == "explain":
                    await self._do_explain(data.get("topic", text))
                    return
        except Exception:
            pass

        await self._say(self.voice.unknown_command(text))

    # ── Actions ───────────────────────────────────────────────────────────────

    async def _do_scan(self) -> None:
        if not self._profile:
            await self._say("No profile here yet — let me initialize first.")
            await self._do_init()
            if not self._profile:
                return

        pb_count = self._count_playbooks()
        await self._say(self.voice.scan_start(pb_count))

        log = self.app.query_one("#chat-log", ChatLog)
        log.system_line(self.voice.thinking())

        try:
            findings, secret_hits = await asyncio.wait_for(
                self._run_scan_async(), timeout=300
            )
        except asyncio.TimeoutError:
            await self._say("Scan timed out. Try on a smaller repo or check the workers.")
            return
        except Exception as e:
            await self._say(f"Something went wrong: {e}")
            return

        self._last_findings = findings

        # Stream each finding narrative with a short pause between
        for finding in findings:
            narrative = self.voice.finding_narrative(finding)
            await self._stream(narrative)
            await asyncio.sleep(0.4)

        # Done summary
        await self._say(self.voice.scan_done(findings, secret_hits))

        # Opinion on what to do first
        if findings:
            opinion = self.voice.findings_summary_opinion(findings)
            if opinion:
                await asyncio.sleep(0.3)
                await self._say(opinion)

        self._load_memory()
        self._refresh_sidebar()

    async def _do_fix(self, finding_id: str) -> None:
        if not finding_id:
            await self._say("Give me the finding ID — e.g. /fix abc12345")
            return
        await self._say(
            f"Asking Codex to patch `{finding_id[:8]}`...\n\n"
            f"Run in your terminal for the full diff:\n"
            f"  descry fix {finding_id}"
        )

    async def _do_feedback(self, finding_id: str, action: str) -> None:
        if not finding_id or not action:
            await self._say("Try: /feedback <id> fp  or  /feedback <id> fix")
            return
        try:
            from descry.commands.feedback import run_feedback
            await run_feedback(self.repo_path, finding_id=finding_id, action=action)
            await self._say(self.voice.feedback_ack(action, finding_id))
            self._load_memory()
            self._refresh_sidebar()
        except Exception as e:
            await self._say(f"Couldn't record that: {e}")

    async def _do_status(self) -> None:
        if not self._profile:
            await self._say("No project here yet. Run /scan to get started.")
            return
        from descry.memory.scheduler import ScheduleStore
        conv = len(self._conventions.get_active_conventions()) if self._conventions else 0
        sched = 0
        runs: list[dict] = []
        if self._memory:
            try:
                s = ScheduleStore(self._memory)
                sched = len(s._data.get("schedules", []))
                for f in sorted(self._memory.history_dir.glob("*.json"), reverse=True)[:3]:
                    if "findings" not in f.name:
                        runs.append(json.loads(f.read_text()))
            except Exception:
                pass
        await self._stream(self.voice.status_narrative(self._profile, conv, sched, runs))

    async def _do_init(self) -> None:
        await self._say("Scanning the repo...")
        log = self.app.query_one("#chat-log", ChatLog)
        log.system_line(self.voice.thinking())
        try:
            from descry.commands.init import run_init
            await run_init(self.repo_path, use_llm=True)
            self._load_memory()
            stack = ", ".join((self._profile.frameworks or self._profile.languages)[:3]) if self._profile else "unknown"
            await self._say(f"Done. Detected {stack}. Type /scan to start.")
            self._refresh_sidebar()
        except Exception as e:
            await self._say(f"Init failed: {e}")

    async def _do_explain(self, topic: str) -> None:
        """Use claude to explain a security topic in plain English."""
        if not shutil.which("claude"):
            await self._say(self.voice.unknown_command(topic))
            return

        log = self.app.query_one("#chat-log", ChatLog)
        log.system_line("thinking...")

        prompt = (
            f"You are Descry, a security agent. Answer this question from a developer in plain English. "
            f"Be direct and practical. Max 4 sentences. No bullet points.\n\nQuestion: {topic}"
        )
        try:
            proc = await asyncio.create_subprocess_exec(
                "claude", "--no-interactive", "--output-format", "text", "-p", prompt,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
            answer = out.decode(errors="replace").strip()
            if answer:
                await self._stream(answer)
                return
        except Exception:
            pass
        await self._say(self.voice.unknown_command(topic))

    async def _do_help(self) -> None:
        await self._stream(
            "/scan                 run a full security scan\n"
            "/fix <id>             ask Codex to patch a finding\n"
            "/feedback <id> fp     mark a finding as a false positive\n"
            "/feedback <id> fix    mark a finding as fixed\n"
            "/status               show what I know about this project\n"
            "/init                 (re)initialize the project profile\n\n"
            "You can also just talk to me — I'll do my best."
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _say(self, text: str) -> None:
        """Write agent message without typewriter (for short replies)."""
        log = self.app.query_one("#chat-log", ChatLog)
        log.agent_label()
        for line in text.split("\n"):
            log.write(f"  [#cccccc]{line}[/]" if line.strip() else "")
        log.write("")

    async def _stream(self, text: str) -> None:
        """Write agent message with typewriter effect."""
        log = self.app.query_one("#chat-log", ChatLog)
        log.agent_label()
        await _typewrite(log, text)
        log.write("")
        self._session.append({"role": "assistant", "content": text})

    def _count_playbooks(self) -> int:
        try:
            from descry.playbooks.loader import PlaybookLoader
            from descry.scanners.inventory import RepoInventory
            builtin = Path(__file__).parent.parent.parent.parent / "playbooks"
            loader = PlaybookLoader(builtin_dir=builtin)
            inv = RepoInventory.scan(self.repo_path)
            return len(loader.filter_applicable(loader.load_all(), inv))
        except Exception:
            return 3

    def _count_open_findings(self) -> int:
        if not self._memory:
            return 0
        try:
            files = sorted(self._memory.history_dir.glob("*-findings.json"), reverse=True)
            if files:
                data = json.loads(files[0].read_text())
                return len([f for f in data if f.get("lifecycle", {}).get("status") == "open"])
        except Exception:
            pass
        return 0

    def _last_run_ts(self) -> str | None:
        if not self._memory:
            return None
        try:
            runs = [
                f for f in sorted(self._memory.history_dir.glob("*.json"), reverse=True)
                if "findings" not in f.name
            ]
            if runs:
                data = json.loads(runs[0].read_text())
                ts = data.get("timestamp", "")
                if ts:
                    delta = datetime.utcnow() - datetime.fromisoformat(ts)
                    mins = int(delta.total_seconds() / 60)
                    if mins < 60:
                        return f"{mins}m ago"
                    if mins < 1440:
                        return f"{mins // 60}h ago"
                    return f"{delta.days}d ago"
        except Exception:
            pass
        return None

    def _refresh_sidebar(self) -> None:
        if not self._profile:
            self.app.update_sidebar(
                project_name=self.repo_path.name,
                stack="not initialized",
                surfaces="run /scan",
            )
            return
        p = self._profile
        stack = ", ".join((p.frameworks or p.languages)[:3]) or "unknown"
        surfs = ", ".join(
            s for s, v in [
                ("auth", p.has_auth), ("payments", p.has_payments),
                ("llm", p.has_llm_features), ("uploads", p.has_file_upload),
            ] if v
        ) or "none detected"
        conv = len(self._conventions.get_active_conventions()) if self._conventions else 0
        self.app.update_sidebar(
            project_name=p.app_purpose or p.repo_name or self.repo_path.name,
            stack=stack,
            surfaces=surfs,
            finding_count=self._count_open_findings(),
            convention_count=conv,
            last_run=self._last_run_ts() or "never",
        )

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
        from descry.commands.scan import _save_history

        store = MemoryStore(self.repo_path)
        profile = ProjectProfile.load(store)
        conventions = ConventionStore(store)
        calibration = CalibrationStore(store)
        schedule = ScheduleStore(store)

        inventory = RepoInventory.scan(self.repo_path, prev_deps=profile.deps)
        secrets = await SecretsScanner().run(self.repo_path)

        pool = WorkerPool(max_concurrent=4, max_per_type=2)
        pool.register(ClaudeWorker())
        pool.register(CodexWorker())
        pool.register(MockWorker())

        builtin = Path(__file__).parent.parent.parent.parent / "playbooks"
        loader = PlaybookLoader(builtin_dir=builtin, user_dir=store.root / "playbooks")
        mission = Planner(loader, schedule).plan("manual", inventory)
        executor = Executor(pool, loader, profile, conventions, calibration, self.repo_path)
        findings = await executor.execute(mission)

        _save_history(store, mission.id, findings)
        schedule.increment_run_count()

        return findings, len(secrets)
