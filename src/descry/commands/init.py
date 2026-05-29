"""swain init — bootstrap a repo."""

from __future__ import annotations

from pathlib import Path

from rich.console import Console
from rich.panel import Panel

from descry.memory.profile import ProjectProfile
from descry.memory.store import MemoryStore
from descry.scanners.inventory import RepoInventory

console = Console()


async def run_init(repo_root: Path, use_llm: bool = True) -> None:
    console.print(
        Panel.fit("[bold cyan]Swain Init[/bold cyan]", subtitle=str(repo_root))
    )

    store = MemoryStore(repo_root)

    # Step 1: deterministic static scan
    console.print("[dim]Scanning repo...[/dim]")
    inventory = RepoInventory.scan(repo_root)

    profile = ProjectProfile(
        languages=inventory.languages,
        frameworks=inventory.frameworks,
        deps=inventory.deps[:100],  # cap stored deps
        deploy_target=inventory.deploy_target,
        db=inventory.db,
        has_auth=inventory.has_auth,
        has_payments=inventory.has_payments,
        has_file_upload=inventory.has_file_upload,
        has_llm_features=inventory.has_llm_features,
        repo_name=repo_root.name,
    )

    detected_stack = ", ".join(profile.frameworks or profile.languages)
    console.print(f"  Detected: [green]{detected_stack}[/green]")
    if profile.deploy_target:
        console.print(f"  Deploy target: [green]{profile.deploy_target}[/green]")
    surfaces = [
        k for k, v in [
            ("auth", profile.has_auth),
            ("payments", profile.has_payments),
            ("file-upload", profile.has_file_upload),
            ("llm", profile.has_llm_features),
        ] if v
    ]
    if surfaces:
        console.print(f"  Surfaces: [yellow]{', '.join(surfaces)}[/yellow]")

    # Step 2: optional LLM bootstrap
    if use_llm:
        await _llm_bootstrap(repo_root, profile)

    profile.save(store)

    # Confirm with user
    console.print()
    console.print("[bold]Inferred priorities:[/bold]")
    for p in profile.user_priorities:
        console.print(f"  • {p}")
    console.print()
    console.print(
        "[dim]Wrote .swain/profile.yaml — edit if anything looks wrong, "
        "then run [bold]swain scan[/bold][/dim]"
    )


async def _llm_bootstrap(repo_root: Path, profile: ProjectProfile) -> None:
    import shutil

    if not shutil.which("claude"):
        console.print(
            "[dim]claude CLI not found — skipping LLM threat model inference[/dim]"
        )
        _set_default_priorities(profile)
        return

    import asyncio
    import json as _json

    readme_text = ""
    for name in ["README.md", "readme.md", "README.txt"]:
        readme = repo_root / name
        if readme.exists():
            readme_text = readme.read_text(errors="ignore")[:2000]
            break

    git_log = ""
    try:
        proc = await asyncio.create_subprocess_exec(
            "git",
            "log",
            "--oneline",
            "-50",
            cwd=repo_root,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
        git_log = out.decode(errors="ignore")
    except Exception as exc:
        console.print(f"[dim]Could not read git history: {exc}[/dim]")

    prompt = f"""\
Analyze this project and output JSON with security priorities.

PROJECT CONTEXT:
Stack: {', '.join(profile.frameworks or profile.languages)}
Surfaces:
- auth={profile.has_auth}
- payments={profile.has_payments}
- llm={profile.has_llm_features}
Deploy: {profile.deploy_target}

README (first 2000 chars):
{readme_text or '(not found)'}

RECENT COMMITS:
{git_log or '(none)'}

Output ONLY this JSON (no explanation):
{{
  "app_purpose": "one sentence description",
  "user_priorities": ["top security concerns for this specific app"],
  "inferred_threat_model": ["top 3 threat scenarios"]
}}
"""
    try:
        proc = await asyncio.create_subprocess_exec(
            "claude", "--output-format", "text", "-p", prompt,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            cwd=repo_root,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=60)
        text = out.decode(errors="ignore").strip()
        # Extract JSON
        idx = text.find("{")
        ridx = text.rfind("}")
        if idx != -1 and ridx != -1:
            data = _json.loads(text[idx : ridx + 1])
            profile.app_purpose = data.get("app_purpose", "")
            profile.user_priorities = data.get("user_priorities", [])
            profile.inferred_threat_model = data.get("inferred_threat_model", [])
            console.print(f"  [dim]App purpose: {profile.app_purpose}[/dim]")
    except Exception as e:
        console.print(f"[dim]LLM bootstrap failed: {e} — using defaults[/dim]")
        _set_default_priorities(profile)


def _set_default_priorities(profile: ProjectProfile) -> None:
    priorities = []
    if profile.has_auth:
        priorities.append("authentication and authorization bypass")
    if profile.has_payments:
        priorities.append("payment logic tampering")
    if profile.has_llm_features:
        priorities.append("prompt injection in LLM features")
    priorities.extend([
        "secrets and credentials exposure",
        "dependency vulnerabilities",
    ])
    profile.user_priorities = priorities[:5]
