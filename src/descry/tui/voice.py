"""Agent voice — converts structured data into humanistic first-person language."""

from __future__ import annotations

import itertools
import random
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from descry.memory.profile import ProjectProfile
    from descry.models import Finding

_THINKING = itertools.cycle([
    "on it...",
    "checking...",
    "one sec...",
    "looking...",
    "give me a moment...",
])

_SEVERITY_WEIGHT = {
    "critical": "this is serious",
    "high": "worth fixing soon",
    "medium": "something to look at",
    "low": "minor thing",
    "info": "heads up",
}

_SCAN_CLEAN = [
    "Clean. Nothing jumped out this time.",
    "All clear. Didn't find anything worth flagging.",
    "Nothing. Either it's clean or I need better playbooks — probably both.",
    "Came up empty. I'll keep watching.",
]


class AgentVoice:
    def greeting(self, profile: ProjectProfile | None, last_run_ts: str | None = None) -> str:
        if profile is None:
            return (
                "Hey. I don't see a project here yet.\n\n"
                "Point me at a repo and I'll take a look — type the path or run /scan."
            )
        stack = ", ".join((profile.frameworks or profile.languages)[:3]) or "your project"
        surfaces = []
        if profile.has_auth:
            surfaces.append("auth")
        if profile.has_payments:
            surfaces.append("payments")
        if profile.has_llm_features:
            surfaces.append("LLM features")

        surface_str = f" I see {', '.join(surfaces)}." if surfaces else ""
        last = f" Last scan was {last_run_ts}." if last_run_ts else " Haven't run a scan yet."

        return (
            f"Hey. I'm looking at your {stack} project.{surface_str}"
            f"{last}\n\nWant me to run a fresh pass? Type /scan."
        )

    def finding_narrative(self, finding: Finding) -> str:
        sev = finding.severity.value
        weight = _SEVERITY_WEIGHT.get(sev, "something")
        file = finding.evidence.file
        line = finding.evidence.line_start

        location = f"`{file}`" + (f":{line}" if line else "")
        data_flow = finding.evidence.data_flow

        lines = [f"[{sev.upper()}] {finding.title}  —  {weight}"]
        lines.append(f"In {location}.")

        if finding.description:
            lines.append(finding.description)
        elif data_flow:
            lines.append(f"Data flow: {data_flow}")

        if finding.exploitability.assessment:
            lines.append(finding.exploitability.assessment)

        if finding.remediation.summary:
            lines.append(f"Fix: {finding.remediation.summary}")

        return "\n".join(lines)

    def scan_start(self, playbook_count: int) -> str:
        return f"Running {playbook_count} check{'s' if playbook_count != 1 else ''} now..."

    def scan_done(self, findings: list, secret_hits: int) -> str:
        if not findings and not secret_hits:
            return random.choice(_SCAN_CLEAN)

        parts = []
        if findings:
            crit = sum(1 for f in findings if f.severity.value == "critical")
            high = sum(1 for f in findings if f.severity.value == "high")
            total = len(findings)
            if crit:
                parts.append(f"{crit} critical")
            if high:
                parts.append(f"{high} high")
            remaining = total - crit - high
            if remaining:
                parts.append(f"{remaining} other")
            count_str = ", ".join(parts) or str(total)
            findings_str = f"Found {count_str} issue{'s' if total != 1 else ''}."
        else:
            findings_str = ""

        secret_str = f" Also caught {secret_hits} secret hit{'s' if secret_hits != 1 else ''} in the static scan — check those first." if secret_hits else ""

        return f"Done. {findings_str}{secret_str}".strip()

    def thinking(self) -> str:
        return next(_THINKING)

    def convention_learned(self, rule: str, file_glob: str) -> str:
        return f"Got it — I'll stop flagging `{rule}` in `{file_glob}` going forward."

    def feedback_ack(self, action: str, finding_id: str) -> str:
        msgs = {
            "fp": f"Noted as a false positive. I'll factor that in next time.",
            "fix": f"Nice. Marked as fixed.",
            "wontfix": f"Understood — won't flag that again.",
            "snooze": f"Snoozed. I'll bring it back up later.",
        }
        return msgs.get(action, f"Got it.")

    def unknown_command(self, text: str) -> str:
        return (
            "I can run a scan, generate a fix, or show you what I've learned.\n\n"
            "Try /scan, /fix <id>, /feedback <id> fp, or /status."
        )

    def status_narrative(
        self,
        profile: ProjectProfile,
        convention_count: int,
        schedule_count: int,
        recent_runs: list[dict],
    ) -> str:
        stack = ", ".join((profile.frameworks or profile.languages)[:3]) or "unknown stack"
        lines = [f"Project: {profile.app_purpose or profile.repo_name} ({stack})"]

        if profile.user_priorities:
            lines.append(f"I'm watching: {', '.join(profile.user_priorities[:3])}")

        lines.append(f"Learned {convention_count} convention{'s' if convention_count != 1 else ''} so far.")
        lines.append(f"{schedule_count} playbook{'s' if schedule_count != 1 else ''} active in schedule.")

        if recent_runs:
            last = recent_runs[0]
            ts = last.get("timestamp", "")[:16]
            count = last.get("finding_count", 0)
            lines.append(f"Last run: {ts} — {count} finding{'s' if count != 1 else ''}.")

        return "\n".join(lines)
