"""Project profile — auto-learned facts about the target repo."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from descry.memory.store import MemoryStore


@dataclass
class ProjectProfile:
    # Stack facts (auto-detected)
    languages: list[str] = field(default_factory=list)
    frameworks: list[str] = field(default_factory=list)
    deps: list[str] = field(default_factory=list)
    deploy_target: str = ""  # vercel, railway, fly, docker, etc.
    db: list[str] = field(default_factory=list)

    # Surface flags
    has_auth: bool = False
    has_payments: bool = False
    has_file_upload: bool = False
    has_llm_features: bool = False

    # Inferred goals (from README + commit messages + chat)
    user_priorities: list[str] = field(default_factory=list)
    inferred_threat_model: list[str] = field(default_factory=list)

    # App identity
    app_purpose: str = ""
    repo_name: str = ""

    @classmethod
    def load(cls, store: MemoryStore) -> ProjectProfile:
        data = store.read_yaml(store.profile_path)
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    def save(self, store: MemoryStore) -> None:
        from dataclasses import asdict
        store.write_yaml(store.profile_path, asdict(self))

    def to_context_block(self) -> str:
        """Render ~200-token context block injected into every worker prompt."""
        lines = [
            f"PROJECT: {self.app_purpose or self.repo_name}",
            f"STACK: {', '.join(self.frameworks or self.languages)}",
        ]
        if self.deploy_target:
            lines.append(f"DEPLOY: {self.deploy_target}")
        if self.db:
            lines.append(f"DB: {', '.join(self.db)}")
        flags = [k for k, v in [
            ("auth", self.has_auth),
            ("payments", self.has_payments),
            ("file-upload", self.has_file_upload),
            ("llm-features", self.has_llm_features),
        ] if v]
        if flags:
            lines.append(f"SURFACES: {', '.join(flags)}")
        if self.user_priorities:
            lines.append(f"USER PRIORITIES: {', '.join(self.user_priorities)}")
        if self.inferred_threat_model:
            lines.append(f"THREAT MODEL: {'; '.join(self.inferred_threat_model[:3])}")
        return "\n".join(lines)
