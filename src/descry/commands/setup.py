"""swain setup - first-run configuration."""

from __future__ import annotations

from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

from descry.memory.config import (
    CONCURRENCY_PRESETS,
    SwainConfig,
    normalize_concurrency,
    normalize_worker_mode,
    setup_completed,
)
from descry.memory.store import MemoryStore

console = Console()


async def run_setup(
    repo_root: Path,
    *,
    worker_mode: str | None = None,
    claude_model: str | None = None,
    codex_model: str | None = None,
    concurrency: str | None = None,
    interactive: bool = True,
    init_profile: bool = True,
) -> SwainConfig:
    store = MemoryStore(repo_root)
    existing = SwainConfig.load(store)

    _render_intro(repo_root)
    _render_worker_choices()

    mode = _choose_worker_mode(worker_mode, existing, interactive)
    selected_claude_model = ""
    if mode in {"claude", "hybrid"}:
        selected_claude_model = _choose_model(
            "Claude",
            existing.claude_model,
            claude_model,
            interactive,
        )
    selected_codex_model = ""
    if mode in {"codex", "hybrid"}:
        selected_codex_model = _choose_model(
            "Codex",
            existing.codex_model,
            codex_model,
            interactive,
        )

    _render_concurrency_choices()
    selected_concurrency = _choose_concurrency(concurrency, existing, interactive)
    max_concurrent, max_per_type = CONCURRENCY_PRESETS[selected_concurrency]

    config = SwainConfig.completed(
        worker_mode=mode,
        claude_model=selected_claude_model,
        codex_model=selected_codex_model,
        concurrency=selected_concurrency,
        max_concurrent=max_concurrent,
        max_per_type=max_per_type,
    )
    config.save(store)

    if init_profile and not store.profile_path.exists():
        await _build_local_profile(repo_root)

    _render_complete(repo_root, config)
    return config


def _render_intro(repo_root: Path) -> None:
    console.print()
    console.print(
        Panel.fit(
            "[bold cyan]Swain setup[/bold cyan]\n\n"
            "Swain is a local AI security lead for repos that are close to "
            "shipping. It looks hardest at auth, billing, uploads, tenant "
            "boundaries, secrets, SQL, and XSS.\n\n"
            "It reads your target repo, runs local deterministic checks first, "
            "then sends focused file copies to your own Claude and/or Codex "
            "CLI workers when you run a real scan.\n\n"
            "It writes memory to .swain/. Scans do not edit your app. "
            "`swain fix` drafts a patch for review; it does not apply it.",
            subtitle=str(repo_root),
        )
    )


def _render_worker_choices() -> None:
    table = Table(title="Choose model workers", show_lines=True)
    table.add_column("Mode", style="bold")
    table.add_column("Use this when")
    table.add_column("Performance and quota impact")
    table.add_row(
        "hybrid",
        "You have both CLIs and want fallback between providers.",
        "Best resilience. Can touch both Claude and Codex quotas during a scan.",
    )
    table.add_row(
        "claude",
        "You want scans to stay on Claude.",
        "Usually strong for security review. Uses Claude quota only.",
    )
    table.add_row(
        "codex",
        "You want scans and patch drafting to stay on Codex.",
        "Keeps the workflow on one CLI. Uses Codex quota only.",
    )
    console.print(table)


def _render_concurrency_choices() -> None:
    table = Table(title="Choose scan speed", show_lines=True)
    table.add_column("Speed", style="bold")
    table.add_column("Behavior")
    table.add_column("Tradeoff")
    table.add_row(
        "careful",
        "One worker call at a time.",
        "Lowest quota burst and easiest to watch. Slower.",
    )
    table.add_row(
        "balanced",
        "Two worker calls can run at once.",
        "Faster. More quota can be spent in parallel.",
    )
    table.add_row(
        "fast",
        "Up to four worker calls can run at once.",
        "Fastest. Highest quota burst.",
    )
    console.print(table)


def _choose_worker_mode(
    value: str | None,
    existing: SwainConfig,
    interactive: bool,
) -> str:
    if value:
        return normalize_worker_mode(value)
    default = existing.worker_mode if existing.setup_completed else "hybrid"
    if not interactive:
        return default
    return Prompt.ask(
        "Worker mode",
        choices=["hybrid", "claude", "codex"],
        default=default,
    )


def _choose_model(
    label: str,
    existing: str,
    value: str | None,
    interactive: bool,
) -> str:
    if value is not None:
        return "" if value == "default" else value.strip()
    if not interactive:
        return existing.strip()

    console.print()
    console.print(f"[bold]{label} model[/bold]")
    console.print(
        "Use the CLI default unless you already know the exact model id your "
        f"{label.lower()} CLI accepts. Bigger reasoning models usually catch "
        "more cross-file issues, but they are slower and can spend more quota. "
        "Faster models are cheaper to try, but need more manual review."
    )
    mode = Prompt.ask(
        f"{label} model choice",
        choices=["default", "custom"],
        default="default" if not existing else "custom",
    )
    if mode == "default":
        return ""
    return Prompt.ask(f"Exact {label} model id", default=existing).strip()


def _choose_concurrency(
    value: str | None,
    existing: SwainConfig,
    interactive: bool,
) -> str:
    if value:
        return normalize_concurrency(value)
    default = existing.concurrency if existing.setup_completed else "careful"
    if not interactive:
        return default
    return Prompt.ask(
        "Scan speed",
        choices=["careful", "balanced", "fast"],
        default=default,
    )


async def _build_local_profile(repo_root: Path) -> None:
    console.print()
    console.print(
        "[dim]Building a local repo profile now. This step does not spend "
        "Claude/Codex quota.[/dim]"
    )
    from descry.commands.init import run_init

    await run_init(repo_root, use_llm=False)


def _render_complete(repo_root: Path, config: SwainConfig) -> None:
    console.print()
    console.print(
        Panel.fit(
            "[bold green]Swain is set up.[/bold green]\n\n"
            f"Workers: {config.worker_summary()}\n"
            "Saved: .swain/config.yaml\n\n"
            "Next:\n"
            f"  swain doctor {repo_root} --no-probe-workers\n"
            f"  swain {repo_root}",
            title="Ready",
        )
    )


__all__ = ["run_setup", "setup_completed"]
