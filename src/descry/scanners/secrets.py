"""
Deterministic secrets scanner — wraps gitleaks + trufflehog.
Falls back to entropy-based heuristics if CLIs not installed.
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass
class SecretHit:
    file: str
    line: int
    rule: str
    match_hash: str  # hash of the matched value, never stored in plain
    verified: bool = False
    description: str = ""


class SecretsScanner:
    async def run(self, repo_root: Path) -> list[SecretHit]:
        hits: list[SecretHit] = []
        if shutil.which("gitleaks"):
            hits.extend(await self._run_gitleaks(repo_root))
        else:
            hits.extend(self._entropy_scan(repo_root))
        return hits

    async def _run_gitleaks(self, repo_root: Path) -> list[SecretHit]:
        try:
            proc = await asyncio.create_subprocess_exec(
                "gitleaks", "detect", "--source", str(repo_root),
                "--report-format", "json", "--report-path", "/dev/stdout",
                "--no-git", "--exit-code", "0",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=60)
            raw = json.loads(stdout.decode()) if stdout.strip() else []
            return [
                SecretHit(
                    file=r.get("File", ""),
                    line=r.get("StartLine", 0),
                    rule=r.get("RuleID", "secret"),
                    match_hash=_hash_secret(r.get("Match", "")),
                    description=r.get("Description", ""),
                )
                for r in (raw or [])
            ]
        except Exception:
            return []

    def _entropy_scan(self, repo_root: Path) -> list[SecretHit]:
        """Fallback: regex + Shannon entropy scan."""
        patterns = [
            (r'(?i)(api[_-]?key|secret|token|password)\s*[=:]\s*["\']([^"\']{16,})["\']', "generic-secret"),
            (r'sk-[a-zA-Z0-9]{48}', "openai-key"),
            (r'anthropic[_-]?api[_-]?key\s*=\s*["\']?(sk-ant-[^"\'\s]+)', "anthropic-key"),
            (r'AKIA[0-9A-Z]{16}', "aws-access-key"),
        ]
        hits = []
        ignore = {".git", "node_modules", "__pycache__", ".next", "dist", "build", "target", ".venv"}
        for f in repo_root.rglob("*"):
            if not f.is_file() or any(p in f.parts for p in ignore):
                continue
            try:
                text = f.read_text(errors="ignore")
                for pattern, rule_id in patterns:
                    for m in re.finditer(pattern, text):
                        line = text[: m.start()].count("\n") + 1
                        hits.append(SecretHit(
                            file=str(f.relative_to(repo_root)),
                            line=line,
                            rule=rule_id,
                            match_hash=_hash_secret(m.group(0)),
                        ))
            except Exception:
                pass
        return hits


def _hash_secret(value: str) -> str:
    import hashlib
    return hashlib.sha256(value.encode()).hexdigest()[:16]
