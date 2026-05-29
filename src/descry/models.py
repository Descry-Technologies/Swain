"""Core domain models — shared across all modules."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, model_validator


class Severity(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class WorkerType(StrEnum):
    CLAUDE = "claude"
    CODEX = "codex"
    SEMGREP = "semgrep"
    GITLEAKS = "gitleaks"
    OSV = "osv"
    MOCK = "mock"


class FindingStatus(StrEnum):
    OPEN = "open"
    FIXED = "fixed"
    WONTFIX = "wontfix"
    FP = "fp"
    SUPPRESSED = "suppressed"


class Evidence(BaseModel):
    file: str
    line_start: int | None = None
    line_end: int | None = None
    anchor: str  # structural anchor — stable across line moves
    snippet_hash: str | None = None
    data_flow: str | None = None
    reachable_routes: list[str] = Field(default_factory=list)


class Exploitability(BaseModel):
    requires_auth: bool = True
    requires_interaction: bool = False
    network_exposed: bool = False
    assessment: str = ""


class Remediation(BaseModel):
    summary: str = ""
    patch_diff: str | None = None
    references: list[str] = Field(default_factory=list)


class Suppression(BaseModel):
    suppressed: bool = False
    reason: str = ""
    expires_at: str | None = None
    suppressed_by: str | None = None
    suppressed_at: datetime | None = None


class FindingLifecycle(BaseModel):
    status: FindingStatus = FindingStatus.OPEN
    introduced_commit: str | None = None
    fixed_commit: str | None = None
    first_seen: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_seen: datetime = Field(default_factory=lambda: datetime.now(UTC))


class FindingSource(BaseModel):
    worker: WorkerType
    model: str | None = None
    playbook: str
    playbook_version: int
    run_id: str | None = None


class Finding(BaseModel):
    schema_version: str = "1.0"
    id: str = ""
    rule: str
    severity: Severity
    confidence: float = Field(ge=0.0, le=1.0)
    title: str
    description: str = ""
    cwe: str | None = None
    owasp: str | None = None
    evidence: Evidence
    exploitability: Exploitability = Field(default_factory=Exploitability)
    remediation: Remediation = Field(default_factory=Remediation)
    suppression: Suppression = Field(default_factory=Suppression)
    lifecycle: FindingLifecycle = Field(default_factory=FindingLifecycle)
    source: FindingSource

    @model_validator(mode="after")
    def compute_id(self) -> Finding:
        if not self.id:
            key = f"{self.rule}:{self.evidence.file}:{self.evidence.anchor}"
            self.id = hashlib.sha256(key.encode()).hexdigest()[:16]
        return self


class WorkerReport(BaseModel):
    """Structured output from a CLI worker subprocess."""

    schema_version: str = "1.0"
    task_id: str
    worker: WorkerType
    playbook: str
    playbook_version: int
    findings: list[Finding] = Field(default_factory=list)
    partial: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class Task(BaseModel):
    id: str
    playbook_id: str
    worker: WorkerType
    files: list[str] = Field(default_factory=list)
    priority: int = 5
    context: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Mission(BaseModel):
    id: str
    trigger: str  # "cron", "pr", "push", "chat", "finding"
    tasks: list[Task] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None


class FeedbackEvent(BaseModel):
    finding_id: str
    action: str  # "fp", "fix", "wontfix", "snooze"
    user: str = "user"
    comment: str = ""
    branch: str = "main"
    rule_version: int = 0
    worker: WorkerType | None = None
    model: str | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
