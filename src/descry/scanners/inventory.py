"""
Deterministic repo inventory — no LLM required.
Builds the code intelligence layer the planner uses for routing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# Dep detection patterns per manifest file
_DEP_MANIFESTS = {
    "package.json": r'"(?P<name>[@\w/-]+)"\s*:\s*"[^"]+"',
    "pyproject.toml": r'(?P<name>[\w-]+)\s*[><=!~^]',
    "requirements.txt": r'^(?P<name>[\w-]+)',
    "Cargo.toml": r'(?P<name>[\w-]+)\s*=',
    "go.mod": r'require\s+(?P<name>\S+)',
}

_FRAMEWORK_SIGNALS: dict[str, list[str]] = {
    "next": ["next", "next.js"],
    "react": ["react", "react-dom"],
    "vue": ["vue"],
    "nuxt": ["nuxt"],
    "fastapi": ["fastapi"],
    "django": ["django"],
    "express": ["express"],
    "hono": ["hono"],
    "supabase": ["@supabase/supabase-js", "supabase"],
    "prisma": ["prisma", "@prisma/client"],
    "drizzle": ["drizzle-orm"],
    "stripe": ["stripe", "@stripe/stripe-js"],
    "clerk": ["@clerk/nextjs", "clerk"],
    "resend": ["resend"],
    "openai": ["openai", "@openai/sdk"],
    "anthropic": ["@anthropic-ai/sdk", "anthropic"],
}

_DEPLOY_SIGNALS = {
    "vercel": ["vercel.json", ".vercel"],
    "railway": ["railway.json", "railway.toml"],
    "fly": ["fly.toml"],
    "docker": ["Dockerfile", "docker-compose.yml"],
    "aws": ["serverless.yml", "cdk.json", "samconfig.toml"],
}

_AUTH_PATTERNS = [
    r"/api/auth",
    r"/login",
    r"/signup",
    r"/register",
    r"useAuth",
    r"withAuth",
    r"middleware.*auth",
    r"jwt",
    r"session",
    r"oauth",
]

_PAYMENT_PATTERNS = [
    r"\bstripe\b",
    r"\bcheckout\b",
    r"\bsubscription(s)?\b",
    r"\binvoice(s)?\b",
    r"\bpayment(s)?\b",
    r"\bbilling\b",
]

_FILE_UPLOAD_PATTERN = (
    r"\b(formdata|form_data|multipart|multer|uploadfile|upload_file)\b"
    r"|type\s*=\s*[\"']file[\"']"
    r"|<input[^>]+file"
)

_LLM_PATTERNS = [r"openai", r"anthropic", r"claude", r"gpt", r"llm", r"completion"]


@dataclass
class RepoInventory:
    repo_root: Path
    languages: list[str] = field(default_factory=list)
    frameworks: list[str] = field(default_factory=list)
    deps: list[str] = field(default_factory=list)
    deploy_target: str = ""
    db: list[str] = field(default_factory=list)
    has_auth: bool = False
    has_payments: bool = False
    has_file_upload: bool = False
    has_llm_features: bool = False
    all_files: list[Path] = field(default_factory=list)
    route_files: list[Path] = field(default_factory=list)
    auth_files: list[Path] = field(default_factory=list)
    risk_events: list[str] = field(default_factory=list)

    @classmethod
    def scan(cls, repo_root: Path, prev_deps: list[str] | None = None) -> RepoInventory:
        inv = cls(repo_root=repo_root)
        inv._collect_files()
        inv._detect_languages()
        inv._detect_deps()
        inv._detect_frameworks()
        inv._detect_deploy()
        inv._detect_surfaces()
        if prev_deps is not None:
            inv._detect_risk_events(prev_deps)
        return inv

    def _collect_files(self) -> None:
        ignore = {
            ".git",
            "node_modules",
            "__pycache__",
            ".venv",
            "dist",
            "build",
            "target",
            ".next",
        }
        self.all_files = [
            f for f in self.repo_root.rglob("*")
            if f.is_file() and not any(p in f.parts for p in ignore)
        ]

    def _detect_languages(self) -> None:
        exts: set[str] = set()
        for f in self.all_files:
            exts.add(f.suffix.lstrip("."))
        lang_map = {
            "ts": "TypeScript",
            "tsx": "TypeScript",
            "js": "JavaScript",
            "jsx": "JavaScript",
            "py": "Python",
            "rs": "Rust",
            "go": "Go",
            "rb": "Ruby",
        }
        self.languages = list({lang_map[e] for e in exts if e in lang_map})

    def _detect_deps(self) -> None:
        found: set[str] = set()
        for fname, pattern in _DEP_MANIFESTS.items():
            for f in self.all_files:
                if f.name == fname:
                    try:
                        text = f.read_text(errors="ignore")
                        found.update(
                            m.group("name")
                            for m in re.finditer(pattern, text, re.MULTILINE)
                        )
                    except (OSError, UnicodeError):
                        continue
        self.deps = sorted(found)

    def _detect_frameworks(self) -> None:
        dep_set = {d.lower() for d in self.deps}
        found = []
        for fw, signals in _FRAMEWORK_SIGNALS.items():
            if any(s in dep_set for s in signals):
                found.append(fw)
        self.frameworks = found
        if any(
            d in dep_set
            for d in ["pg", "postgres", "postgresql", "@supabase/supabase-js"]
        ):
            self.db.append("postgres")
        if any(d in dep_set for d in ["mysql", "mysql2"]):
            self.db.append("mysql")
        if any(d in dep_set for d in ["prisma", "@prisma/client", "drizzle-orm"]):
            self.db.append("orm")

    def _detect_deploy(self) -> None:
        existing = {f.name for f in self.all_files}
        for target, signals in _DEPLOY_SIGNALS.items():
            if any(s in existing for s in signals):
                self.deploy_target = target
                break

    def _detect_surfaces(self) -> None:
        texts: list[str] = []
        for f in self.all_files:
            if f.suffix in {".ts", ".tsx", ".js", ".jsx", ".py"}:
                try:
                    text = f.read_text(errors="ignore")
                    texts.append(text.lower())
                    if any(
                        re.search(p, text, re.IGNORECASE)
                        for p in _AUTH_PATTERNS
                    ):
                        self.auth_files.append(f)
                except (OSError, UnicodeError):
                    continue

        combined = "\n".join(texts)
        path_text = "\n".join(
            str(f.relative_to(self.repo_root)).lower() for f in self.all_files
        )
        surface_text = f"{combined}\n{path_text}"
        self.has_auth = bool(re.search("|".join(_AUTH_PATTERNS), combined))
        self.has_payments = (
            "stripe" in self.frameworks
            or bool(re.search("|".join(_PAYMENT_PATTERNS), surface_text))
        )
        self.has_llm_features = bool(re.search("|".join(_LLM_PATTERNS), combined))
        self.has_file_upload = bool(
            re.search(_FILE_UPLOAD_PATTERN, surface_text)
        )

        # Route files: Next.js app router, API routes
        self.route_files = [
            f for f in self.all_files
            if "app/" in str(f)
            and f.name in ("route.ts", "route.js", "page.tsx", "page.jsx")
            or "pages/api/" in str(f)
        ]

    def _detect_risk_events(self, prev_deps: list[str]) -> None:
        new_deps = set(self.deps) - set(prev_deps)
        for d in new_deps:
            if any(
                s in d.lower()
                for s in ["auth", "jwt", "session", "oauth", "clerk"]
            ):
                self.risk_events.append(f"new-auth-dep:{d}")
            if any(s in d.lower() for s in ["stripe", "paddle", "payment"]):
                self.risk_events.append(f"new-payment-dep:{d}")
        if len(self.route_files) > 0:
            self.risk_events.append("has-routes")
