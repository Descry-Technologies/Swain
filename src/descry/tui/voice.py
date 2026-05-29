"""
Agent voice — Descry's character layer.

The goal: feel like a senior security engineer who's also a good communicator.
Direct. Has opinions. Not corporate. Not a scanner with a chatbox.

Rules for writing voice copy here:
- First person, present tense
- Contractions always (I've, it's, you're, won't)
- No "I have detected", "I have identified" — just "I found", "there's"
- Critical findings: short sentences. Urgent. No hedging.
- Clean scans: a bit of relief. Not robotic "No findings detected."
- Never say "please" or "kindly" or "certainly"
- Vary sentence length — one-word sentences are fine when they land right
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from descry.memory.profile import ProjectProfile
    from descry.models import Finding


# ── Thinking phrases ──────────────────────────────────────────────────────────
_THINKING = [
    "on it...",
    "checking...",
    "one sec...",
    "looking...",
    "give me a moment...",
    "let me see...",
    "running that now...",
]

# ── Clean scan variety ────────────────────────────────────────────────────────
_SCAN_CLEAN = [
    "Clean. Nothing jumped out.",
    "All clear this time.",
    "Nothing. Could be clean, could mean I need sharper rules. Watching.",
    "Came up empty. I'll keep an eye on it.",
    "Nothing new. Good.",
]

# ── Severity openers ─────────────────────────────────────────────────────────
_SEV_OPENERS = {
    "critical": [
        "This one's bad.",
        "Stop. This needs attention now.",
        "Real problem here.",
        "This is the kind of thing that gets exploited.",
    ],
    "high": [
        "Worth fixing soon.",
        "This one matters.",
        "I'd prioritize this.",
        "Don't let this sit.",
    ],
    "medium": [
        "Something to look at.",
        "Not urgent, but don't forget it.",
        "Middling severity, but real.",
        "Low priority for now, but keep it on the list.",
    ],
    "low": [
        "Minor.",
        "Small one.",
        "Low risk, easy fix.",
        "Cleanup-level thing.",
    ],
    "info": [
        "Heads up.",
        "Just an observation.",
        "FYI —",
    ],
}

# ── Greeting variants based on context ───────────────────────────────────────
_GREET_NO_PROJECT = [
    "Hey. Don't see a project here yet — point me at a repo and I'll start looking.",
    "Hey. No project loaded. Drop a path or type /scan to point me somewhere.",
]

_GREET_FIRST_TIME = [
    "Hey. First time here — I'll need a minute to learn your stack. Run /scan and I'll get started.",
    "Hey. Haven't scanned this one yet. Run /scan and I'll take a look.",
]

_GREET_RETURNING_CLEAN = [
    "Hey. Last scan was clean. Want me to run another pass?",
    "Hey. Nothing flagged last time. Run /scan to check again.",
]

_GREET_RETURNING_FINDINGS = [
    "Hey. I've got {count} open finding{plural} from the last scan. Want to go through them, or run a fresh pass?",
    "Hey. Still {count} thing{plural} open from before. Type /scan to recheck or /status to review.",
]


class AgentVoice:

    # ── Greetings ─────────────────────────────────────────────────────────────

    def greeting(
        self,
        profile: "ProjectProfile | None",
        last_run_ts: str | None = None,
        open_findings: int = 0,
    ) -> str:
        if profile is None:
            return random.choice(_GREET_NO_PROJECT)

        stack = ", ".join((profile.frameworks or profile.languages)[:3]) or "your project"
        surfs = [s for s, v in [
            ("auth", profile.has_auth),
            ("payments", profile.has_payments),
            ("LLM features", profile.has_llm_features),
        ] if v]

        context = f"I'm looking at your {stack} project."
        if surfs:
            context += f" I see {', '.join(surfs)} in the mix."

        if not last_run_ts:
            base = random.choice(_GREET_FIRST_TIME)
            return f"{context}\n\n{base}"

        if open_findings > 0:
            p = "s" if open_findings != 1 else ""
            base = random.choice(_GREET_RETURNING_FINDINGS).format(count=open_findings, plural=p)
        else:
            base = random.choice(_GREET_RETURNING_CLEAN)

        return f"{context} Last scan was {last_run_ts}.\n\n{base}"

    # ── Findings ──────────────────────────────────────────────────────────────

    def finding_narrative(self, finding: "Finding") -> str:
        sev = finding.severity.value
        opener = random.choice(_SEV_OPENERS.get(sev, ["Found something."]))

        file = finding.evidence.file
        line = finding.evidence.line_start
        loc = f"`{file}`" + (f" line {line}" if line else "")

        parts = [f"{opener}\n"]
        parts.append(f"{finding.title} — in {loc}.")

        if finding.description:
            parts.append(finding.description)
        elif finding.evidence.data_flow:
            parts.append(f"Path: {finding.evidence.data_flow}")

        if finding.exploitability.assessment:
            parts.append(finding.exploitability.assessment)
        elif finding.exploitability.network_exposed and not finding.exploitability.requires_auth:
            parts.append("It's network-exposed and doesn't require auth. That's the worst combination.")
        elif finding.exploitability.network_exposed:
            parts.append("Network-exposed, though auth is required.")

        if finding.remediation.summary:
            parts.append(f"Fix: {finding.remediation.summary}")

        conf = finding.confidence
        if conf < 0.6:
            parts.append(f"(Confidence is lower on this one — {conf:.0%}. Worth a manual look before acting.)")

        return "\n".join(parts)

    def findings_summary_opinion(self, findings: list) -> str:
        """After listing all findings, give a prioritization opinion."""
        if not findings:
            return ""

        critical = [f for f in findings if f.severity.value == "critical"]
        high = [f for f in findings if f.severity.value == "high"]
        net_exposed_noauth = [
            f for f in findings
            if f.exploitability.network_exposed and not f.exploitability.requires_auth
        ]

        if critical:
            return f"I'd start with the critical one{'s' if len(critical) > 1 else ''}. Everything else can wait."
        if net_exposed_noauth:
            t = net_exposed_noauth[0].title
            return f"Of these, the one I'd fix first is the {t} — it's exposed without auth."
        if high:
            return f"The high-severity one{'s' if len(high) > 1 else ''} should go on the list for this sprint."
        return "None of these are on fire, but I'd work through them in order."

    # ── Scan lifecycle ────────────────────────────────────────────────────────

    def scan_start(self, playbook_count: int) -> str:
        opts = [
            f"Running {playbook_count} check{'s' if playbook_count != 1 else ''}...",
            f"On it. {playbook_count} check{'s' if playbook_count != 1 else ''} queued.",
            f"Starting {playbook_count} check{'s' if playbook_count != 1 else ''}.",
        ]
        return random.choice(opts)

    def scan_done(self, findings: list, secret_hits: int) -> str:
        if not findings and not secret_hits:
            return random.choice(_SCAN_CLEAN)

        parts = []

        if findings:
            crit = sum(1 for f in findings if f.severity.value == "critical")
            high = sum(1 for f in findings if f.severity.value == "high")
            total = len(findings)
            breakdown = []
            if crit:
                breakdown.append(f"{crit} critical")
            if high:
                breakdown.append(f"{high} high")
            rest = total - crit - high
            if rest:
                breakdown.append(f"{rest} other")
            summary = ", ".join(breakdown) if breakdown else str(total)
            parts.append(f"Found {summary} issue{'s' if total != 1 else ''}.")

        if secret_hits:
            parts.append(
                f"Also caught {secret_hits} secret hit{'s' if secret_hits != 1 else ''} in the static scan — check those first."
            )

        return " ".join(parts)

    # ── Feedback / learning ───────────────────────────────────────────────────

    def thinking(self) -> str:
        return random.choice(_THINKING)

    def convention_learned(self, rule: str, file_glob: str) -> str:
        opts = [
            f"Got it — I'll stop flagging `{rule}` in `{file_glob}`.",
            f"Noted. Won't flag that pattern in `{file_glob}` again.",
            f"Learned. `{rule}` in `{file_glob}` is accepted here.",
        ]
        return random.choice(opts)

    def feedback_ack(self, action: str, finding_id: str) -> str:
        msgs = {
            "fp": random.choice([
                "Noted as a false positive. I'll factor it in.",
                "Got it — not a real issue. I'll remember that.",
                "False positive recorded. I'll adjust.",
            ]),
            "fix": random.choice([
                "Nice. Marked as fixed.",
                "Good. Off the list.",
                "Marked fixed.",
            ]),
            "wontfix": random.choice([
                "Understood. Won't surface that again.",
                "Noted — accepted risk. Won't flag it.",
                "Got it. Leaving it alone.",
            ]),
            "snooze": random.choice([
                "Snoozed. I'll bring it back up later.",
                "Noted. I'll resurface it in a bit.",
            ]),
        }
        return msgs.get(action, "Got it.")

    # ── Status ────────────────────────────────────────────────────────────────

    def status_narrative(
        self,
        profile: "ProjectProfile",
        convention_count: int,
        schedule_count: int,
        recent_runs: list[dict],
    ) -> str:
        stack = ", ".join((profile.frameworks or profile.languages)[:3]) or "unknown"
        lines = []

        if profile.app_purpose:
            lines.append(f"{profile.app_purpose} — {stack}.")
        else:
            lines.append(f"{profile.repo_name or 'Project'} — {stack}.")

        if profile.user_priorities:
            lines.append(f"I'm watching: {', '.join(profile.user_priorities[:3])}.")

        if convention_count:
            lines.append(
                f"I've learned {convention_count} convention{'s' if convention_count != 1 else ''} so far — "
                f"patterns this codebase accepts."
            )
        else:
            lines.append("No conventions learned yet. Give me feedback on findings and I'll calibrate.")

        lines.append(f"{schedule_count} playbook{'s' if schedule_count != 1 else ''} active.")

        if recent_runs:
            last = recent_runs[0]
            ts = last.get("timestamp", "")[:16].replace("T", " ")
            count = last.get("finding_count", 0)
            if count:
                lines.append(f"Last run: {ts} — {count} finding{'s' if count != 1 else ''}.")
            else:
                lines.append(f"Last run: {ts} — clean.")

        return "\n".join(lines)

    # ── Unknown / help ────────────────────────────────────────────────────────

    def unknown_command(self, text: str) -> str:
        opts = [
            "Not sure what you mean. Try /scan, /fix <id>, /feedback <id> fp, or /status.",
            "I didn't catch that. /scan runs a check, /status shows what I know, /fix <id> patches a finding.",
            "Hmm. I can scan, fix, or show status — what do you need?",
        ]
        return random.choice(opts)

    def cant_do_yet(self, thing: str) -> str:
        return f"Can't do {thing!r} yet. On the roadmap."
