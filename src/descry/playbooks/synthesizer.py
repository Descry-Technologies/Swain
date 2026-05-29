"""
Playbook synthesizer — generates new playbooks from observed patterns.

Rules:
- Only synthesizes when pattern seen N>=3 times with >=2 confirmed TPs
- Generated playbooks go to .descry/playbooks/generated/ (pending review)
- Requires shadow_runs_required > 0 before activation
- Uses claude worker to write the YAML
- Never synthesizes for critical/high severity patterns
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml


SYNTHESIS_MIN_TPS = 3
SYNTHESIS_SHADOW_RUNS = 5  # shadow runs before generated playbook activates


class PlaybookSynthesizer:
    def __init__(self, generated_dir: Path) -> None:
        self.generated_dir = generated_dir

    def should_synthesize(self, pattern_observations: list[dict]) -> bool:
        tps = [o for o in pattern_observations if o.get("confirmed_tp")]
        return len(tps) >= SYNTHESIS_MIN_TPS

    def build_synthesis_prompt(self, pattern: dict[str, Any], examples: list[dict]) -> str:
        positive_examples = "\n\n".join(
            f"Example {i+1} (confirmed finding):\n```\n{e.get('snippet', '')}\n```\nRule: {e.get('rule', '')}\nReason: {e.get('reason', '')}"
            for i, e in enumerate(examples[:3])
        )
        return f"""\
You are writing a Descry security playbook in YAML format.

A pattern has been observed {len(examples)} times in a codebase and confirmed as a true positive.
Write a targeted playbook that detects this specific pattern.

CONFIRMED PATTERN:
Rule family: {pattern.get('rule_family', 'sast')}
File type: {pattern.get('file_glob', '**/*')}
Description: {pattern.get('description', '')}

POSITIVE EXAMPLES (code that should trigger a finding):
{positive_examples}

Write a YAML playbook following this schema:
- id: generated.<unique-id>  (slug form, no spaces)
- version: 1
- author: descry-synthesizer
- description: <what this detects>
- worker: claude
- output_schema: finding.v1
- generated: true
- shadow_runs_required: {SYNTHESIS_SHADOW_RUNS}
- applies_when: <appropriate conditions>
- files:
    include: [<relevant globs>]
    exclude: [<noise paths like tests, fixtures>]
- prompt: |
    <clear prompt asking claude to find this specific pattern>
    Must ask for JSON output matching finding.v1 schema.
- tests:
    - fixture: <describe a positive fixture>
      expect_finding_count: 1
    - fixture: <describe a negative fixture>
      expect_finding_count: 0

Output ONLY valid YAML. No explanation.
"""

    def save_generated(self, yaml_content: str, pattern_id: str) -> Path:
        slug = hashlib.sha256(pattern_id.encode()).hexdigest()[:8]
        filename = f"generated-{slug}-{datetime.utcnow().strftime('%Y%m%d')}.yaml"
        path = self.generated_dir / filename
        path.write_text(yaml_content)
        return path
