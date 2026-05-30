"""
Swain TUI — interactive agent interface.

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
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rich.markup import escape
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import Input, RichLog, Static

from descry.memory.coworker import DecisionRecord, FixQueueItem
from descry.orchestrator.lead import LeadOrchestrationError, LeadOrchestrator
from descry.resources import builtin_playbooks_dir
from descry.tui.voice import AgentVoice

_COMMANDS = (
    ("/scan", "identify, fix, verify"),
    ("/scan details", "show the worker trace from the last scan"),
    ("/status", "show mission, watch, decisions, and queue"),
    ("/fix <id>", "redraft one patch"),
    ("/launch-card", "export a shareable launch verdict SVG"),
    ("/feedback <id> fp", "mark a false positive"),
    ("/feedback <id> fix", "mark a finding fixed"),
    ("/watch", "configure git polling for this repo"),
    ("/setup", "configure Claude/Codex workers"),
    ("/update", "update Swain"),
    ("/init", "rebuild the project profile"),
    ("/help", "show command help"),
)

# ── Typewriter timing ────────────────────────────────────────────────────────

_CHAR_DELAY   = 0.018   # base per-character delay (s)
_WORD_DELAY   = 0.04    # extra pause at word boundaries
_COMMA_DELAY  = 0.12    # pause after comma
_PERIOD_DELAY = 0.22    # pause after sentence-ending punctuation
_NEWLINE_DELAY = 0.15   # pause between lines


async def _typewrite(log: ChatLog, text: str) -> None:
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
        self.write("[bold #00d4aa]Swain[/]")

    def user_label(self, text: str) -> None:
        self.write(f"[#555555]you  [#888888]{text}[/]")
        self.write("")

    def system_line(self, text: str) -> None:
        self.write(f"  [italic #444444]{text}[/]")

    def scan_event(self, text: str) -> None:
        if text.startswith("["):
            self.write(f"  {text}")
            return
        if " waiting for " in text:
            self.write(f"  [#777777]queue[/] [#888888]{text}[/]")
        elif " reviewing " in text:
            self.write(f"  [bold #00d4aa]subagent[/] [#888888]{text}[/]")
        elif " returned " in text:
            self.write(f"  [#2fdd92]done[/] [#888888]{text}[/]")
        elif "failed" in text or text.startswith("warning:"):
            self.write(f"  [#f0b429]warn[/] [#888888]{text}[/]")
        else:
            self.write(f"  [#777777]• {text}[/]")


@dataclass(frozen=True)
class ScanRunResult:
    findings: list
    secret_hits: int
    warnings: list[str]


@dataclass(frozen=True)
class PatchDraftStatus:
    finding_id: str
    title: str
    ok: bool
    message: str
    path: Path | None = None
    applied: bool = False
    source_files: tuple[str, ...] = ()


class Sidebar(Vertical):
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
    scan_phase: reactive[str] = reactive("idle")
    worker_setup: reactive[str] = reactive("not configured")
    subagents: reactive[str] = reactive("idle")
    last_event: reactive[str] = reactive("none")

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._task_status: dict[str, str] = {}

    def compose(self) -> ComposeResult:
        yield Static("[bold #00d4aa]Swain[/]\n", id="sb-brand")
        yield Static("", id="sb-project")
        yield Static("", id="sb-stack")
        yield Static("", id="sb-surfaces")
        yield Static("", id="sb-findings")
        yield Static("", id="sb-conventions")
        yield Static("", id="sb-last-run")
        yield Static("", id="sb-scan-phase")
        yield Static("", id="sb-worker-setup")
        yield Static("", id="sb-subagents")
        yield Static("", id="sb-last-event")

    def on_mount(self) -> None:
        self._refresh_rows()

    def _refresh_rows(self) -> None:
        if not self.is_mounted:
            return

        def row(wid: str, label: str, val: str) -> None:
            self.query_one(f"#{wid}", Static).update(
                f"[#555555]{label}[/]\n[#cccccc]{val or '—'}[/]\n"
            )
        row("sb-project",     "project",    self.project_name)
        row("sb-stack",       "stack",      self.stack)
        row("sb-surfaces",    "surfaces",   self.surfaces)
        findings_label = str(self.finding_count) if self.finding_count else "none open"
        convention_label = (
            f"{self.convention_count} "
            f"convention{'s' if self.convention_count != 1 else ''}"
        )
        row("sb-findings",    "findings",   findings_label)
        row("sb-conventions", "learned",    convention_label)
        row("sb-last-run",    "last scan",  self.last_run)
        row("sb-scan-phase",  "scan",       self.scan_phase)
        row("sb-worker-setup", "workers",   self.worker_setup)
        row("sb-subagents",   "subagents",  self.subagents)
        row("sb-last-event",  "last event", self.last_event)

    def record_scan_event(self, text: str) -> None:
        self.last_event = text[:140]
        if text.startswith("indexing repo"):
            self._task_status.clear()
            self.scan_phase = "indexing repo"
        elif text.startswith("worker setup:"):
            self.worker_setup = text.removeprefix("worker setup:").strip()
        elif text.startswith("fixes:"):
            self.scan_phase = text.removeprefix("fixes:").strip()
        elif text.startswith("planned ") or text.startswith("mission "):
            self.scan_phase = text
        elif text.startswith("queue:"):
            self.scan_phase = text
        elif text.startswith("warning:"):
            self.scan_phase = "needs attention"
        elif ": starting with " in text:
            playbook = text.split(":", 1)[0]
            self._task_status[playbook] = "queued"
        elif " waiting for " in text and ":" in text:
            playbook, rest = text.split(":", 1)
            worker = rest.strip().removeprefix("waiting for ").split(" ", 1)[0]
            self._task_status[playbook] = f"{worker} waiting"
        elif " reviewing " in text and ":" in text:
            playbook, rest = text.split(":", 1)
            worker = rest.strip().split(" reviewing ", 1)[0]
            self._task_status[playbook] = f"{worker} reviewing"
            self.scan_phase = f"{worker} subagent active"
        elif " returned " in text and ":" in text:
            playbook, rest = text.split(":", 1)
            worker = rest.strip().split(" returned ", 1)[0]
            self._task_status[playbook] = f"{worker} done"
        elif " failed " in text and ":" in text:
            playbook, rest = text.split(":", 1)
            worker = rest.strip().split(" failed ", 1)[0]
            self._task_status[playbook] = f"{worker} failed"
            self.scan_phase = "worker issue"
        self.subagents = self._format_subagents()

    def _format_subagents(self) -> str:
        if not self._task_status:
            return "idle"
        rows = [
            f"{name}: {status}"
            for name, status in sorted(self._task_status.items())[:6]
        ]
        remaining = len(self._task_status) - len(rows)
        if remaining > 0:
            rows.append(f"+{remaining} more")
        return "\n".join(rows)

    def watch_project_name(self, _: str) -> None: self._refresh_rows()
    def watch_stack(self, _: str) -> None: self._refresh_rows()
    def watch_surfaces(self, _: str) -> None: self._refresh_rows()
    def watch_finding_count(self, _: int) -> None: self._refresh_rows()
    def watch_convention_count(self, _: int) -> None: self._refresh_rows()
    def watch_last_run(self, _: str) -> None: self._refresh_rows()
    def watch_scan_phase(self, _: str) -> None: self._refresh_rows()
    def watch_worker_setup(self, _: str) -> None: self._refresh_rows()
    def watch_subagents(self, _: str) -> None: self._refresh_rows()
    def watch_last_event(self, _: str) -> None: self._refresh_rows()


# ── App ───────────────────────────────────────────────────────────────────────

class SwainApp(App):
    CSS_PATH = Path(__file__).parent / "theme.tcss"
    TITLE = "Swain"

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit", show=True),
        Binding("ctrl+l", "clear_chat", "Clear", show=False),
    ]

    def __init__(self, repo_path: Path | None = None) -> None:
        super().__init__()
        self.repo_path = repo_path or Path.cwd()
        self.voice = AgentVoice()
        self._agent: SwainAgent | None = None

    def compose(self) -> ComposeResult:
        yield Static(
            f"[dim]Swain[/]  [#00d4aa]●[/]  {self.repo_path.name}",
            id="status-bar",
        )
        with Horizontal(id="main"):
            yield ChatLog(id="chat-log", markup=True, highlight=False, wrap=True)
            yield Sidebar(id="sidebar")
        yield Static("", id="command-suggestions")
        yield Input(placeholder="Ask Swain anything...", id="message-input")
        yield Static(
            "[#333333]ctrl+c exit  ·  /scan identify/fix/verify  ·  "
            "/status  ·  /scan details[/]",
            id="footer",
        )

    async def on_mount(self) -> None:
        self.query_one("#command-suggestions", Static).display = False
        self.query_one("#message-input", Input).focus()
        self._agent = SwainAgent(self)
        # Run greeting in background so UI renders first
        self.run_worker(self._agent.start(), exclusive=True, name="greeting")

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "message-input":
            return
        suggestions = command_suggestions_for(event.value)
        panel = self.query_one("#command-suggestions", Static)
        panel.update(suggestions)
        panel.display = bool(suggestions)

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if not text:
            return
        event.input.value = ""
        suggestions = self.query_one("#command-suggestions", Static)
        suggestions.update("")
        suggestions.display = False
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

    def record_scan_event(self, text: str) -> None:
        self.query_one("#sidebar", Sidebar).record_scan_event(text)


# ── Agent ─────────────────────────────────────────────────────────────────────

class SwainAgent:
    """
    All agent logic lives here.

    Key design decisions:
    - NLU for ambiguous input goes through claude (if available), not regex
    - Session history is kept so the agent can reference earlier messages
    - Findings are surfaced with opinions, not just listed
    """

    def __init__(self, app: SwainApp) -> None:
        self.app = app
        self.voice = app.voice
        self.repo_path = app.repo_path
        self._lead = LeadOrchestrator(self.repo_path)
        self._profile = None
        self._memory = None
        self._conventions = None
        # Session conversation history for context-aware responses
        self._session: list[dict[str, str]] = []
        self._last_findings: list = []
        self._last_scan_events: list[str] = []
        self._scan_visible_keys: set[str] = set()

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        self._load_memory()
        open_findings = self._count_open_findings()
        msg = self.voice.greeting(
            self._profile,
            repo_name=self.repo_path.name,
            last_run_ts=self._last_run_ts(),
            open_findings=open_findings,
        )
        await self._stream(msg)
        self._refresh_sidebar()

    def _load_memory(self) -> None:
        try:
            from descry.memory.conventions import ConventionStore
            from descry.memory.profile import ProjectProfile
            from descry.memory.store import MemoryStore

            profile_path = self.repo_path / ".swain" / "profile.yaml"
            if not profile_path.exists():
                self._profile = None
                self._conventions = None
                self._memory = None
                return

            self._memory = MemoryStore(self.repo_path)
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
        elif cmd in ("/scan fresh", "scan fresh", "/rescan", "rescan"):
            await self._do_scan(use_cache=False)
        elif cmd.startswith(("/scan details", "scan details", "/details", "details")):
            await self._do_scan_details(self._scan_detail_focus(text))
        elif cmd.startswith(("/fix ", "fix ")):
            fid = text.split(None, 1)[1].strip() if " " in text else ""
            await self._do_fix(fid)
        elif cmd in ("/launch-card", "launch-card"):
            await self._do_launch_card()
        elif cmd.startswith(("/feedback ", "feedback ")):
            parts = text.split()
            if len(parts) >= 3:
                await self._do_feedback(parts[1], parts[2])
            else:
                await self._say("Try: /feedback <id> fp  or  /feedback <id> fix")
        elif cmd in ("/watch", "watch"):
            await self._handle_natural("watch this repo")
        elif cmd in ("/status", "status"):
            await self._do_status()
        elif cmd in ("/init", "init"):
            await self._do_init()
        elif cmd in ("/setup", "setup"):
            await self._do_setup()
        elif cmd in ("/update", "update"):
            await self._do_update()
        elif cmd in ("help", "/help"):
            await self._do_help()
        else:
            # Ambiguous input — use NLU if claude is available, else fallback
            await self._handle_natural(text)

    async def _handle_natural(self, text: str) -> None:
        """Use claude to interpret the intent, then route to the right action."""
        intent = self._lead.interpret(text)
        if intent.action == "scan":
            await self._do_scan(
                objective=text,
                launch_focus=intent.launch_focus,
            )
            return
        if intent.action == "status":
            await self._do_status()
            return
        if intent.action == "draft_fix":
            await self._do_fix(intent.finding_id)
            return
        if intent.action == "details":
            await self._do_scan_details("")
            return
        if intent.action == "record_preference":
            decision = self._lead.record_correction(text)
            await self._say(
                "Noted. I'll treat that as project context for future scans.\n"
                f"Decision: {decision.summary}"
            )
            return
        if intent.action == "watch":
            state = self._lead.enable_watch()
            await self._say(
                "Watch is configured for this repo.\n\n"
                "To keep it running in the foreground:\n"
                f"  swain watch {self.repo_path}\n\n"
                "For a Linux user service:\n"
                f"  swain daemon install {self.repo_path}\n"
                f"Polling interval: {state.interval_s}s."
            )
            self._refresh_sidebar()
            return

        local_answer = self._try_local_answer(text)
        if local_answer:
            await self._say(local_answer)
            return

        if not shutil.which("claude"):
            await self._say(self.voice.unknown_command(text))
            return

        # Build a short NLU prompt with session context
        history_str = "\n".join(
            f"{m['role']}: {m['content']}" for m in self._session[-6:]
        )
        nlu_prompt = f"""\
You are the intent classifier for a security agent called Swain.
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
                "claude",
                "--output-format",
                "text",
                "-p",
                nlu_prompt,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=20)
            raw = out.decode(errors="replace").strip()
            # Extract JSON
            s, e = raw.find("{"), raw.rfind("}")
            if s != -1 and e != -1:
                data = json.loads(raw[s : e + 1])
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
            await self._say(self.voice.unknown_command(text))
            return

        await self._say(self.voice.unknown_command(text))

    # ── Actions ───────────────────────────────────────────────────────────────

    async def _do_scan(
        self,
        *,
        objective: str = "manual scan",
        launch_focus: bool = False,
        fix_depth: int = 0,
        prior_fix_statuses: list[PatchDraftStatus] | None = None,
        use_cache: bool = True,
        focus_files: set[str] | None = None,
    ) -> None:
        if not self._profile:
            await self._say("No profile here yet — let me initialize first.")
            await self._do_init()
            if not self._profile:
                return

        pb_count = self._count_playbooks()
        self._last_scan_events = []
        self._scan_visible_keys = set()
        await self._say(self.voice.scan_start(pb_count))

        log = self.app.query_one("#chat-log", ChatLog)
        log.system_line(self.voice.thinking())

        try:
            result = await self._lead.run_recon(
                trigger="manual",
                objective=objective,
                launch_focus=launch_focus,
                use_cache=use_cache,
                focus_files=focus_files,
                on_event=self._scan_event,
            )
        except TimeoutError:
            await self._say(
                "Scan timed out. Try on a smaller repo or check the workers."
            )
            return
        except LeadOrchestrationError as e:
            await self._say(str(e))
            return
        except Exception as e:
            await self._say(f"Something went wrong: {e}")
            return

        self._last_findings = result.findings

        await self._stream(self._scan_overview(result))
        fix_statuses = await self._draft_fix_queue(result.fix_queue)
        all_fix_statuses = [*(prior_fix_statuses or []), *fix_statuses]

        self._load_memory()
        self._refresh_sidebar()

        verify_files = self._verification_files(fix_statuses)
        if fix_depth < 1 and verify_files:
            await self._say(
                "Verifying applied fixes against the changed source files. "
                "Unchanged worker results stay cached."
            )
            await self._do_scan(
                objective="verify applied fixes",
                launch_focus=launch_focus,
                fix_depth=fix_depth + 1,
                prior_fix_statuses=all_fix_statuses,
                focus_files=verify_files,
            )
            return

        await self._stream(
            self._final_verdict(
                result,
                all_fix_statuses,
                verification_pending=(
                    any(status.applied for status in fix_statuses) and not verify_files
                ),
            )
        )

    async def _do_scan_details(self, focus: str = "") -> None:
        if not self._last_scan_events:
            await self._say("No scan detail yet. Run /scan first.")
            return

        focus_lower = focus.lower()
        general: list[str] = []
        grouped: dict[str, list[str]] = {}
        order: list[str] = []
        for event in self._last_scan_events:
            playbook, _ = self._split_playbook_event(event)
            if playbook:
                if playbook not in grouped:
                    grouped[playbook] = []
                    order.append(playbook)
                grouped[playbook].append(event)
            else:
                general.append(event)

        lines = ["Hidden worker log from the last scan."]
        if focus:
            lines[0] += f" Filter: {focus}"
        lines.append("")
        if general and not focus:
            lines.append("Scan setup")
            lines.extend(f"- {event}" for event in general[:12])

        matched = 0
        for playbook in order:
            label = self._playbook_label(playbook)
            haystack = f"{playbook} {label}".lower()
            if focus_lower and focus_lower not in haystack:
                continue
            matched += 1
            lines.append("")
            lines.append(f"{label} ({playbook})")
            lines.extend(f"- {event}" for event in grouped[playbook])

        if focus and matched == 0:
            lines.append("No matching playbook. Try /scan details auth.")
        elif not focus:
            lines.append("")
            lines.append("Tip: use /scan details auth or /scan details payments.")

        await self._stream("\n".join(lines))

    async def _do_fix(self, finding_id: str) -> None:
        if not finding_id:
            finding_id = self._lead.next_fix_id()
        if not finding_id:
            await self._say(
                "I don't have a queued fix yet. Run /scan first; I'll draft "
                "the queue automatically when findings come back."
            )
            return
        await self._say(
            "Checking finding "
            f"`{finding_id[:8]}`..."
        )
        try:
            from descry.commands.fix import (
                generate_patch_suggestion,
                resolve_patch_target,
                write_patch_draft,
            )

            target = resolve_patch_target(self.repo_path, finding_id)
            if not target.ok:
                await self._say(target.message)
                return
            await self._say(target.message + " Asking Codex now.")

            suggestion = await generate_patch_suggestion(
                self.repo_path,
                finding_id,
                show_status=False,
                target=target,
            )
        except Exception as e:
            await self._say(f"Couldn't draft that fix: {e}")
            return
        if not suggestion.ok:
            await self._say(suggestion.message)
            return
        patch_path = write_patch_draft(self.repo_path, finding_id, suggestion.diff)
        await self._say(
            "Patch draft saved. I did not apply it.\n\n"
            f"`{self._display_path(patch_path)}`"
        )

    async def _draft_fix_queue(
        self,
        fix_queue: list[FixQueueItem],
    ) -> list[PatchDraftStatus]:
        if not fix_queue:
            return []

        total = len(fix_queue)
        await self._say(
            f"Fixing {total} finding{'s' if total != 1 else ''}. "
            "I'll apply patches that pass git's clean-apply check."
        )

        from descry.commands.fix import (
            apply_patch_draft,
            cached_failed_fix_attempt,
            generate_patch_suggestion,
            record_fix_attempt,
            resolve_patch_target,
            write_patch_draft,
        )

        statuses: list[PatchDraftStatus] = []
        targets = []
        skipped: list[PatchDraftStatus] = []
        for item in fix_queue:
            try:
                target = resolve_patch_target(self.repo_path, item.finding_id)
            except Exception as e:
                target = None
                message = f"couldn't check target: {e}"
            else:
                message = target.message if target else "couldn't check target"
            if target and target.ok:
                cached_failure = cached_failed_fix_attempt(
                    self.repo_path,
                    item.finding_id,
                    target,
                )
                if cached_failure is not None:
                    skipped.append(
                        PatchDraftStatus(
                            finding_id=item.finding_id,
                            title=item.title,
                            ok=False,
                            message=(
                                "already tried on unchanged files: "
                                f"{cached_failure.message}"
                            ),
                            path=cached_failure.patch_path,
                            source_files=self._target_source_files(target),
                        )
                    )
                    continue
                targets.append((item, target))
            else:
                skipped.append(
                    PatchDraftStatus(
                        finding_id=item.finding_id,
                        title=item.title,
                        ok=False,
                        message=message,
                    )
                )

        if skipped:
            skip_label = self._skipped_fix_label(skipped)
            self._fix_progress(
                event=f"fixes: skipped {len(skipped)} {skip_label}",
                line=(
                    f"[#f0b429]skip[/] {len(skipped)} finding"
                    f"{'s' if len(skipped) != 1 else ''} {skip_label}"
                ),
            )
            statuses.extend(skipped)

        for index, (item, target) in enumerate(targets, start=1):
            short_id = item.finding_id[:8]
            self._fix_progress(
                event=f"fixes: asking codex {index}/{len(targets)} {short_id}",
                line=(
                    f"[#00d4aa]fix[/] {index}/{total} "
                    f"[#888888]{escape(short_id)}[/] asking Codex"
                ),
            )
            try:
                suggestion = await generate_patch_suggestion(
                    self.repo_path,
                    item.finding_id,
                    show_status=False,
                    target=target,
                )
                message = suggestion.message
            except Exception as e:
                suggestion = None
                message = f"couldn't draft: {e}"

            if suggestion and suggestion.ok:
                patch_path = write_patch_draft(
                    self.repo_path,
                    item.finding_id,
                    suggestion.diff,
                )
                apply_result = apply_patch_draft(self.repo_path, patch_path)
                statuses.append(
                    PatchDraftStatus(
                        finding_id=item.finding_id,
                        title=item.title,
                        ok=apply_result.applied,
                        message=apply_result.message,
                        path=patch_path,
                        applied=apply_result.applied,
                        source_files=self._target_source_files(target),
                    )
                )
                record_fix_attempt(
                    self.repo_path,
                    item.finding_id,
                    target,
                    applied=apply_result.applied,
                    message=apply_result.message,
                    outcome="applied" if apply_result.applied else "apply_failed",
                    patch_path=patch_path,
                )
                if apply_result.applied:
                    self._fix_progress(
                        event=f"fixes: applied {index}/{len(targets)} {short_id}",
                        line=(
                            f"[#2fdd92]done[/] {index}/{total} "
                            f"[#888888]{escape(short_id)}[/] applied"
                        ),
                    )
                else:
                    self._fix_progress(
                        event=f"fixes: saved {index}/{len(targets)} {short_id}",
                        line=(
                            f"[#f0b429]warn[/] {index}/{total} "
                            f"[#888888]{escape(short_id)}[/] saved patch, "
                            "not applied"
                        ),
                    )
                continue

            statuses.append(
                PatchDraftStatus(
                    finding_id=item.finding_id,
                    title=item.title,
                    ok=False,
                    message=message,
                    source_files=self._target_source_files(target),
                )
            )
            if suggestion is not None and self._should_remember_fix_failure(message):
                record_fix_attempt(
                    self.repo_path,
                    item.finding_id,
                    target,
                    applied=False,
                    message=message,
                    outcome="draft_failed",
                )
            elif suggestion is None and self._should_remember_fix_failure(message):
                record_fix_attempt(
                    self.repo_path,
                    item.finding_id,
                    target,
                    applied=False,
                    message=message,
                    outcome="exception",
                )
            self._fix_progress(
                event=f"fixes: failed {index}/{total} {short_id}",
                line=(
                    f"[#f0b429]warn[/] {index}/{total} "
                    f"[#888888]{escape(short_id)}[/] "
                    f"{escape(self._short_title(message, limit=90))}"
                ),
            )
            if "codex CLI not found" in message:
                break

        await self._stream(self._fix_draft_summary(statuses, total))
        return statuses

    def _should_remember_fix_failure(self, message: str) -> bool:
        lowered = message.lower()
        return not any(
            marker in lowered
            for marker in (
                "codex cli not found",
                "not authenticated",
                "please authenticate",
                "login required",
                "log in",
                "api key",
                "quota",
                "rate limit",
            )
        )

    def _verification_files(self, statuses: list[PatchDraftStatus]) -> set[str]:
        files: set[str] = set()
        for status in statuses:
            if status.applied:
                files.update(status.source_files)
        return files

    def _target_source_files(self, target: Any) -> tuple[str, ...]:
        files: list[str] = []
        for file in getattr(target, "files", ()):
            try:
                files.append(file.relative_to(self.repo_path).as_posix())
            except ValueError:
                files.append(str(file))
        return tuple(files)

    def _fix_progress(self, *, event: str, line: str) -> None:
        self._last_scan_events.append(event)
        self.app.record_scan_event(event)
        log = self.app.query_one("#chat-log", ChatLog)
        log.scan_event(line)

    def _fix_draft_summary(
        self,
        statuses: list[PatchDraftStatus],
        total: int,
    ) -> str:
        applied = [status for status in statuses if status.applied]
        saved = [
            status for status in statuses
            if status.path and not status.applied
        ]
        failed = [status for status in statuses if not status.ok]

        lines: list[str] = []
        if applied:
            lines.append(
                f"Applied {len(applied)}/{total} fix"
                f"{'es' if len(applied) != 1 else ''}."
            )
            for status in applied[:5]:
                if status.path is None:
                    continue
                lines.append(
                    f"- `{status.finding_id[:8]}` {self._short_title(status.title)} "
                    f"({self._display_path(status.path)})"
                )
            if len(applied) > 5:
                lines.append(f"- {len(applied) - 5} more applied fix(es)")

        if saved:
            if lines:
                lines.append("")
            lines.append(
                f"Saved {len(saved)} patch "
                f"file{'s' if len(saved) != 1 else ''} that did not apply cleanly."
            )

        if failed:
            if lines:
                lines.append("")
            lines.append(
                f"Skipped {len(failed)} "
                f"finding{'s' if len(failed) != 1 else ''}:"
            )
            for label, count in self._fix_failure_groups(failed):
                lines.append(f"- {count} {label}")
            if len(statuses) < total:
                lines.append(f"- {total - len(statuses)} not attempted")

        if not lines:
            return "No patch drafts were created."
        if applied:
            lines.append("")
            lines.append("Run /scan again to verify what remains.")
        return "\n".join(lines)

    def _fix_failure_groups(
        self,
        failed: list[PatchDraftStatus],
    ) -> list[tuple[str, int]]:
        groups: dict[str, int] = {}
        for status in failed:
            label = self._fix_failure_label(status.message)
            groups[label] = groups.get(label, 0) + 1
        return sorted(groups.items(), key=lambda item: (-item[1], item[0]))

    def _fix_failure_label(self, message: str) -> str:
        lowered = message.lower()
        if "already tried on unchanged files" in lowered:
            return "already tried on unchanged files"
        if "real source file" in lowered or "doesn't exist" in lowered:
            return "need fresh scan evidence"
        if "codex cli not found" in lowered:
            return "need Codex CLI authentication"
        if "did not return a patch" in lowered:
            return "had no usable patch from Codex"
        if "timed out" in lowered:
            return "timed out while drafting"
        if "did not apply cleanly" in lowered or "apply failed" in lowered:
            return "did not apply cleanly"
        return "need manual review"

    def _skipped_fix_label(self, skipped: list[PatchDraftStatus]) -> str:
        groups = self._fix_failure_groups(skipped)
        if len(groups) == 1:
            return groups[0][0]
        return "need review"

    def _final_verdict(
        self,
        result: Any,
        fix_statuses: list[PatchDraftStatus],
        *,
        verification_pending: bool = False,
    ) -> str:
        findings = result.findings
        secret_hits = len(result.secret_hits)
        warnings = result.warnings
        applied = sum(1 for status in fix_statuses if status.applied)
        could_not_fix = sum(1 for status in fix_statuses if not status.applied)
        open_count = len(findings) + secret_hits
        has_blocker = secret_hits > 0 or any(
            finding.severity.value in {"critical", "high"}
            for finding in findings
        )

        if (
            not verification_pending
            and not warnings
            and open_count == 0
            and could_not_fix == 0
        ):
            verdict = "READY"
            next_step = "Next: ship, then run /scan again after risky changes."
        elif has_blocker:
            verdict = "BLOCKED"
            next_step = "Next: review the remaining blockers, then run /scan again."
        elif verification_pending:
            verdict = "NEEDS REVIEW"
            next_step = "Next: run /scan again to verify applied fixes."
        else:
            verdict = "NEEDS REVIEW"
            next_step = "Next: review skipped items or worker warnings, then /scan."

        lines = [
            f"VERDICT: {verdict}",
            f"Fixed: {applied}",
            f"Still open: {open_count}",
            f"Could not fix: {could_not_fix}",
        ]
        if warnings:
            lines.append(f"Worker warnings: {len(warnings)}")
        lines.extend([
            "",
            "I applied only patches that passed `git apply --check`.",
            "I did not commit anything.",
            next_step,
        ])
        return "\n".join(lines)

    async def _do_launch_card(self) -> None:
        try:
            from descry.commands.launch_card import run_launch_card

            output = self.repo_path / "swain-launch-card.svg"
            if not run_launch_card(self.repo_path, out_path=output):
                await self._say(
                    "I need a Swain profile before I can make a launch card."
                )
                return
        except Exception as e:
            await self._say(f"Couldn't export the launch card: {e}")
            return
        await self._say(
            "Launch card exported.\n\n"
            f"`{output}`"
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
        conv = (
            len(self._conventions.get_active_conventions())
            if self._conventions
            else 0
        )
        sched = 0
        runs: list[dict] = []
        if self._memory:
            try:
                s = ScheduleStore(self._memory)
                sched = len(s._data.get("schedules", []))
                history_files = sorted(
                    self._memory.history_dir.glob("*.json"),
                    reverse=True,
                )
                for f in history_files[:3]:
                    if "findings" not in f.name:
                        runs.append(json.loads(f.read_text()))
            except Exception:
                runs = []
        await self._stream(
            self._status_with_coworker_state(
                self.voice.status_narrative(self._profile, conv, sched, runs)
            )
        )

    async def _do_init(self) -> None:
        await self._say("Scanning the repo...")
        log = self.app.query_one("#chat-log", ChatLog)
        log.system_line(self.voice.thinking())
        try:
            from descry.commands.init import run_init
            await run_init(self.repo_path, use_llm=True)
            self._load_memory()
            stack = (
                ", ".join((self._profile.frameworks or self._profile.languages)[:3])
                if self._profile
                else "unknown"
            )
            await self._say(f"Done. Detected {stack}. Type /scan to start.")
            self._refresh_sidebar()
        except Exception as e:
            await self._say(f"Init failed: {e}")

    async def _do_setup(self) -> None:
        await self._say(
            "Setup runs in the terminal because it asks interactive questions "
            "about Claude, Codex, models, and scan speed.\n\n"
            f"Run:\n  swain setup {self.repo_path}"
        )

    async def _do_update(self) -> None:
        await self._say(
            "Updates run in the terminal so you can see the git pull and "
            "reinstall output.\n\nRun:\n  swain update"
        )

    async def _do_explain(self, topic: str) -> None:
        """Use claude to explain a security topic in plain English."""
        if not shutil.which("claude"):
            await self._say(self.voice.unknown_command(topic))
            return

        log = self.app.query_one("#chat-log", ChatLog)
        log.system_line("thinking...")

        prompt = (
            "You are Swain, a security agent. Answer this question from a "
            "developer in plain English. Be direct and practical. Max 4 "
            f"sentences. No bullet points.\n\nQuestion: {topic}"
        )
        try:
            proc = await asyncio.create_subprocess_exec(
                "claude",
                "--output-format",
                "text",
                "-p",
                prompt,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
            answer = out.decode(errors="replace").strip()
            if answer:
                await self._stream(answer)
                return
        except Exception:
            await self._say(self.voice.unknown_command(topic))
            return
        await self._say(self.voice.unknown_command(topic))

    async def _do_help(self) -> None:
        await self._stream(self.voice.help_text())

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _say(self, text: str) -> None:
        """Write agent message without typewriter (for short replies)."""
        log = self.app.query_one("#chat-log", ChatLog)
        log.agent_label()
        for line in text.split("\n"):
            log.write(f"  [#cccccc]{line}[/]" if line.strip() else "")
        log.write("")

    def _scan_event(self, text: str) -> None:
        self._last_scan_events.append(text)
        self.app.record_scan_event(text)
        visible = self._visible_scan_line(text)
        if not visible:
            return
        log = self.app.query_one("#chat-log", ChatLog)
        log.scan_event(visible)

    def _visible_scan_line(self, text: str) -> str | None:
        if text.startswith("indexing repo"):
            return self._once("stage:index", "[#777777]prep[/] mapping the repo")
        if text.startswith("repo profile:"):
            return self._once(
                "stage:profile",
                f"[#777777]scope[/] "
                f"{escape(text.removeprefix('repo profile:').strip())}",
            )
        if text.startswith("running local secret sweep"):
            return self._once(
                "stage:secrets",
                "[#777777]local[/] checking for obvious secrets first",
            )
        if text.startswith("local secret sweep returned"):
            return (
                f"[#2fdd92]done[/] "
                f"{escape(text.replace('local secret sweep ', ''))}"
            )
        if text.startswith("worker setup:"):
            return self._once(
                "stage:workers",
                f"[#777777]workers[/] "
                f"{escape(text.removeprefix('worker setup:').strip())}",
            )
        if text.startswith("planned "):
            return None
        if text.startswith("queue:"):
            return self._once(
                "stage:queue",
                f"[#777777]checks[/] {escape(self._compact_queue(text))}",
            )
        if text.startswith("model workers can spend"):
            return None
        if text.startswith("mission "):
            return None
        if text.startswith("warning:"):
            return self._visible_warning(text)

        playbook, rest = self._split_playbook_event(text)
        if not playbook or not rest:
            return None
        label = self._playbook_label(playbook)
        if rest.startswith("starting with "):
            return None
        if " reviewing " in rest:
            worker, file_part = rest.split(" reviewing ", 1)
            count = file_part.split(" file", 1)[0]
            return self._once(
                f"task:{playbook}:{worker}:reviewing",
                f"[bold #00d4aa]work[/] {escape(label)}: "
                f"{escape(worker)} reviewing {escape(count)} files",
            )
        if " returned " in rest:
            worker, finding_part = rest.split(" returned ", 1)
            count = finding_part.split(" finding", 1)[0]
            if count == "0":
                return None
            return (
                f"[#2fdd92]done[/] {escape(label)}: {escape(worker)} "
                f"returned {escape(count)} findings"
            )
        if " failed - " in rest:
            worker, reason = rest.split(" failed - ", 1)
            return (
                f"[#f0b429]warn[/] {escape(label)}: {escape(worker)} "
                f"{escape(self._clean_worker_reason(reason))}"
            )
        if rest.startswith("disabled ") and " for this scan" in rest:
            return f"[#f0b429]warn[/] {escape(rest)}"
        if rest.startswith("no ") and " worker available" in rest:
            return f"[#f0b429]warn[/] {escape(label)}: {escape(rest)}"
        return None

    def _visible_warning(self, text: str) -> str | None:
        warning = text.removeprefix("warning:").strip()
        playbook = warning.split(" ", 1)[0] if warning else ""
        label = self._playbook_label(playbook) if "." in playbook else ""
        if "retrying with reduced file scope" in warning and label:
            return (
                f"[#f0b429]retry[/] {escape(label)}: smaller file set after "
                "unparsable output"
            )
        return None

    def _once(self, key: str, line: str) -> str | None:
        if key in self._scan_visible_keys:
            return None
        self._scan_visible_keys.add(key)
        return line

    def _compact_queue(self, text: str) -> str:
        raw = text.removeprefix("queue:").strip()
        if not raw or raw == "empty":
            return "no model checks queued"
        labels = [self._playbook_label(item.strip()) for item in raw.split(",")]
        if len(labels) <= 5:
            return ", ".join(labels)
        return ", ".join(labels[:5]) + f", +{len(labels) - 5} more"

    def _split_playbook_event(self, text: str) -> tuple[str, str]:
        if ":" not in text:
            return "", ""
        playbook, rest = text.split(":", 1)
        playbook = playbook.strip()
        if not playbook.startswith(("sast.", "secrets.")):
            return "", ""
        return playbook, rest.strip()

    def _playbook_label(self, playbook: str) -> str:
        labels = {
            "secrets.scan": "Secrets",
            "sast.auth.python": "Auth",
            "sast.file-upload": "Uploads",
            "sast.payments": "Payments",
            "sast.sql-injection": "SQL injection",
            "sast.tenant-isolation": "Tenant isolation",
            "sast.xss.react": "React XSS",
        }
        return labels.get(
            playbook,
            playbook.removeprefix("sast.").replace(".", " ").replace("-", " ").title(),
        )

    def _clean_worker_reason(self, reason: str) -> str:
        reason = reason.strip().rstrip(".")
        if reason == "timed out":
            return "timed out"
        if "could not parse" in reason or "parse" in reason:
            return "returned output I could not read as findings"
        if reason.startswith("exit "):
            return reason
        return reason[:100]

    def _scan_detail_focus(self, text: str) -> str:
        lowered = text.lower()
        for prefix in ("/scan details", "scan details", "/details", "details"):
            if lowered.startswith(prefix):
                return text[len(prefix):].strip()
        return ""

    def _display_path(self, path: Path) -> str:
        try:
            return path.relative_to(self.repo_path).as_posix()
        except ValueError:
            return str(path)

    def _short_title(self, text: str, *, limit: int = 72) -> str:
        clean = " ".join(str(text).split())
        if len(clean) <= limit:
            return clean
        return clean[: limit - 1].rstrip() + "…"

    def _format_decision_log(self, decisions: list[DecisionRecord]) -> str:
        lines = ["Decision log."]
        for decision in decisions[-6:]:
            lines.append(f"- {decision.level.value}: {decision.summary}")
            if decision.rationale:
                lines.append(f"  Why: {decision.rationale}")
            if decision.next_step:
                lines.append(f"  Next: {decision.next_step}")
        return "\n".join(lines)

    def _scan_overview(self, result: Any) -> str:
        findings = result.findings
        secret_hits = len(result.secret_hits)
        warnings = result.warnings
        fix_queue = getattr(result, "fix_queue", [])
        lines = ["Scan complete."]
        summary = self.voice.scan_done(findings, secret_hits)
        if summary:
            lines.append(summary)
        if warnings:
            lines.append(
                f"{len(warnings)} worker warning"
                f"{'s' if len(warnings) != 1 else ''}; "
                "use `/scan details` for the trace."
            )
        if findings:
            lines.append("")
            lines.append(f"Fix queue: {len(fix_queue) or len(findings)}")
            for finding in findings[:3]:
                lines.append(
                    "- "
                    f"{finding.severity.value.upper()} `{finding.id[:8]}` "
                    f"{finding.title} "
                    f"({finding.evidence.file}:{finding.evidence.line_start or '?'}, "
                    f"{finding.confidence:.0%})"
                )
            if len(findings) > 3:
                lines.append(f"- {len(findings) - 3} more finding(s)")
        elif secret_hits:
            lines.extend([
                "",
                "Static secret hits need manual review before anything else.",
            ])
        next_step = (
            ""
            if fix_queue
            else self.voice.scan_next_step(findings, secret_hits)
        )
        if next_step:
            lines.extend(["", next_step])
        return "\n".join(line for line in lines if line is not None)

    def _status_with_coworker_state(self, base: str) -> str:
        try:
            snapshot = self._lead.status_snapshot()
        except Exception:
            return base
        lines = [base, ""]
        ledger = snapshot.ledger
        if ledger.phase.value == "idle":
            lines.append("I'm idle right now.")
        else:
            lines.append(
                f"Current mission: {ledger.phase.value} — "
                f"{ledger.latest_summary or ledger.active_objective}."
            )
        if snapshot.fix_queue:
            first = snapshot.fix_queue[0]
            lines.append(
                f"Top queued finding: `{first.finding_id[:8]}` — {first.title}."
            )
        else:
            lines.append("Fix queue is empty.")
        if snapshot.watch_state.enabled:
            lines.append(
                f"Watch is enabled every {snapshot.watch_state.interval_s}s."
            )
        if snapshot.decisions:
            lines.append("Latest decision: " + snapshot.decisions[0].summary + ".")
        return "\n".join(lines)

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
            loader = PlaybookLoader(builtin_dir=builtin_playbooks_dir())
            inv = RepoInventory.scan(self.repo_path)
            return len(loader.filter_applicable(loader.load_all(), inv))
        except Exception:
            return 3

    def _try_local_answer(self, text: str) -> str:
        lowered = text.strip().lower()
        if not lowered:
            return ""

        priority_phrases = (
            "what should i fix",
            "fix first",
            "prioritize",
            "highest risk",
            "most important",
        )
        if any(phrase in lowered for phrase in priority_phrases):
            if self._last_findings:
                opinion = self.voice.findings_summary_opinion(self._last_findings)
                return (
                    f"{opinion}\n\n"
                    "Run /scan again and I'll recheck, rebuild the queue, and "
                    "draft patch files automatically."
                )
            return "Run /scan first. I need fresh findings before I can rank anything."

        if "launch" in lowered or "ship" in lowered or "market" in lowered:
            return (
                "Before shipping, I want a clean pass on auth, payments, uploads, "
                "secrets, and tenant/data access. Run /scan and I'll draft fixes "
                "for anything I queue."
            )

        return ""

    def _count_open_findings(self) -> int:
        if not self._memory:
            return 0
        try:
            files = sorted(
                self._memory.history_dir.glob("*-findings.json"),
                reverse=True,
            )
            if files:
                data = json.loads(files[0].read_text())
                return len([
                    f for f in data
                    if f.get("lifecycle", {}).get("status") == "open"
                ])
        except Exception:
            return 0
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
                    parsed = datetime.fromisoformat(ts)
                    if parsed.tzinfo is None:
                        parsed = parsed.replace(tzinfo=UTC)
                    delta = datetime.now(UTC) - parsed
                    mins = int(delta.total_seconds() / 60)
                    if mins < 60:
                        return f"{mins}m ago"
                    if mins < 1440:
                        return f"{mins // 60}h ago"
                    return f"{delta.days}d ago"
        except Exception:
            return None
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
        conv = (
            len(self._conventions.get_active_conventions())
            if self._conventions
            else 0
        )
        self.app.update_sidebar(
            project_name=p.app_purpose or p.repo_name or self.repo_path.name,
            stack=stack,
            surfaces=surfs,
            finding_count=self._count_open_findings(),
            convention_count=conv,
            last_run=self._last_run_ts() or "never",
        )

    async def _run_scan_async(self) -> ScanRunResult:
        from descry.commands.scan import _save_history
        from descry.memory.calibration import CalibrationStore
        from descry.memory.config import SwainConfig
        from descry.memory.conventions import ConventionStore
        from descry.memory.profile import ProjectProfile
        from descry.memory.scheduler import ScheduleStore
        from descry.memory.store import MemoryStore
        from descry.orchestrator.executor import Executor
        from descry.orchestrator.planner import Planner
        from descry.playbooks.loader import PlaybookLoader
        from descry.scanners.inventory import RepoInventory
        from descry.scanners.secrets import SecretsScanner
        from descry.workers.configured_pool import build_worker_pool

        store = MemoryStore(self.repo_path)
        config = SwainConfig.load(store)
        profile = ProjectProfile.load(store)
        conventions = ConventionStore(store)
        calibration = CalibrationStore(store)
        schedule = ScheduleStore(store)

        self._scan_event("indexing repo and detecting risky surfaces")
        inventory = RepoInventory.scan(self.repo_path, prev_deps=profile.deps)
        stack = ", ".join(inventory.frameworks or inventory.languages) or "unknown"
        self._scan_event(
            f"repo profile: {len(inventory.all_files)} files, stack={stack}"
        )
        self._scan_event("running local secret sweep before model workers")
        secrets = await SecretsScanner().run(self.repo_path)
        self._scan_event(
            f"local secret sweep returned {len(secrets)} hit"
            f"{'s' if len(secrets) != 1 else ''}"
        )
        self._scan_event(f"worker setup: {config.worker_summary()}")
        pool = build_worker_pool(config)

        loader = PlaybookLoader(
            builtin_dir=builtin_playbooks_dir(),
            user_dir=store.root / "playbooks",
        )
        mission = Planner(loader, schedule).plan("manual", inventory)
        task_names = ", ".join(task.playbook_id for task in mission.tasks)
        file_count = sum(len(task.files) for task in mission.tasks)
        self._scan_event(
            f"planned {len(mission.tasks)} model playbook"
            f"{'s' if len(mission.tasks) != 1 else ''} over {file_count} "
            f"file reference{'s' if file_count != 1 else ''}"
        )
        self._scan_event(f"queue: {task_names or 'empty'}")
        self._scan_event(
            "model workers can spend Claude/Codex quota; worker calls are shown below"
        )
        executor = Executor(
            pool,
            loader,
            profile,
            conventions,
            calibration,
            self.repo_path,
        )
        findings = await executor.execute(mission, on_event=self._scan_event)

        _save_history(store, mission.id, findings)
        schedule.increment_run_count()

        return ScanRunResult(
            findings=findings,
            secret_hits=len(secrets),
            warnings=executor.task_warnings,
        )


def command_suggestions_for(value: str) -> str:
    if not value.startswith("/"):
        return ""
    query = value.strip().lower()
    matches = [
        (command, description)
        for command, description in _COMMANDS
        if query == "/" or command.startswith(query)
    ]
    if not matches:
        return "[#777777]No matching command[/]"
    return "\n".join(
        f"[#00d4aa]{command}[/] [#777777]{description}[/]"
        for command, description in matches
    )
