from descry.models import (
    Evidence,
    Exploitability,
    Finding,
    FindingSource,
    Severity,
    WorkerType,
)
from descry.tui.voice import AgentVoice


def _finding(severity: Severity = Severity.HIGH) -> Finding:
    return Finding(
        rule="sast.auth.python",
        severity=severity,
        confidence=0.92,
        title="Tenant access check is missing",
        evidence=Evidence(
            file="backend/app/api/v1/tenants.py",
            line_start=42,
            anchor="GET /tenant/{id}",
        ),
        exploitability=Exploitability(
            requires_auth=True,
            network_exposed=True,
            assessment="A logged-in user can request another tenant by ID.",
        ),
        source=FindingSource(
            worker=WorkerType.CLAUDE,
            playbook="sast.auth.python",
            playbook_version=1,
        ),
    )


def test_uninitialized_greeting_names_the_repo_and_first_scan_job() -> None:
    text = AgentVoice().greeting(None, repo_name="henri")

    assert "henri" in text
    assert "/scan" in text or "first scan" in text


def test_finding_narrative_includes_actionable_finding_id() -> None:
    finding = _finding()

    text = AgentVoice().finding_narrative(finding)

    assert finding.id[:8] in text
    assert "ID:" in text


def test_scan_next_step_says_fix_queue_is_automatic() -> None:
    finding = _finding()

    text = AgentVoice().scan_next_step([finding], 0)

    assert "drafting patch files" in text
    assert "/fix" not in text


def test_scan_incomplete_does_not_claim_clean() -> None:
    text = AgentVoice().scan_incomplete(["sast.payments parse error: no JSON"])

    assert "don't trust this scan" in text
    assert "not the same as clean" in text
    assert "sast.payments" in text
