# Install

Swain should feel like Claude Code: install once, then type `swain`.

```bash
curl -fsSL https://raw.githubusercontent.com/Descry-Technologies/Swain/main/install.sh | sh
cd /path/to/your/repo
swain
```

The installer is source-based under the hood. It clones Swain into
`~/.swain/source`, installs the global `swain` command, and uses `uv` internally
so regular users do not need to type `uv run ...`.

The first `swain` launch runs setup before opening the TUI. Setup explains what
Swain reads and writes, asks whether scans should use Claude CLI, Codex CLI, or
hybrid mode, lets you keep CLI-default models or enter exact model ids, and asks
how aggressively scans should spend quota in parallel.
It also builds the initial project profile with local scanning only, so setup
does not spend model quota.

Update later without PyPI:

```bash
swain update
```

## Prerequisites

- Python 3.11 or newer
- Git
- `curl` or `wget`
- Optional: authenticated `claude` and/or `codex` CLIs for real scans
- Optional advanced path: `ANTHROPIC_API_KEY` and/or `OPENAI_API_KEY` if you
  choose direct API runtime during setup
- Optional: `uv` if you are contributing from a checkout
- Optional: ImageMagick `convert` only when regenerating `scan-flow.gif`

The offline demo does not require live Claude/Codex quota.

## First Demo

```bash
swain demo
```

What this proves:

- Swain can find its bundled demo app and playbooks.
- `doctor --no-probe-workers` validates setup without spending model quota.
- `status` shows the demo history fixture and a fix-first
  recommendation.
- `scan --mock` replays bundled launch-risk findings without Claude/Codex.

To open the demo TUI:

```bash
swain demo --tui
```

## First Real Repo

Run setup and open the agent:

```bash
swain /path/to/your/repo
```

To rerun setup without opening the TUI:

```bash
swain setup /path/to/your/repo
```

Inside the TUI, use `/scan`. For non-interactive output:

```bash
swain doctor /path/to/your/repo
swain scan /path/to/your/repo --output markdown
swain status /path/to/your/repo
```

Real scans use your local Claude/Codex CLIs. Quota, auth, and local CLI behavior
come from those tools, not from a Swain-hosted service.

CLI runtime is the main product path. Direct API runtime is available in setup
for advanced users who prefer API keys and exact model ids:

```bash
swain setup /path/to/your/repo --mode codex --codex-runtime api --codex-model gpt-5
```

API mode sends selected source snippets inline to the provider API instead of
starting the local CLI worker.

## Common Failures

No `.swain/config.yaml`:

```text
No .swain/config.yaml yet
```

Run setup:

```bash
swain setup /path/to/your/repo
```

No `.swain/profile.yaml`:

```text
No .swain/profile.yaml found. Run swain setup or swain scan first.
```

For the public demo, `examples/launchpad-saas` already includes a profile. For
your own repo, run:

```bash
swain setup /path/to/your/repo
```

Claude quota or auth unavailable:

```text
claude: quota/auth issue
```

Run `swain doctor /path/to/your/repo` to make the failure explicit. Swain can
still use Codex when available. If neither worker is usable, run `swain demo` or
wait for quota/auth to recover.

Missing Codex:

```text
codex CLI not found
```

Install and authenticate Codex before using `swain fix <id>` or the TUI's
automatic patching after `/scan`. Scan demos can still run with `--mock`, and
real scans can use Claude if available.

Missing ImageMagick:

```text
ImageMagick `convert` is required to generate scan-flow.gif.
```

This only affects demo asset regeneration:

```bash
uv run python scripts/capture_demo_assets.py
```

The CLI, tests, source install, and scans do not require ImageMagick.

Updater cannot find managed source:

```text
No managed Swain source checkout found.
```

Run the installer again:

```bash
curl -fsSL https://raw.githubusercontent.com/Descry-Technologies/Swain/main/install.sh | sh
```

## Contributor Checkout

Use this path only when hacking on Swain itself:

```bash
git clone https://github.com/Descry-Technologies/Swain.git
cd swain
uv sync
uv run swain doctor examples/launchpad-saas --no-probe-workers
uv run swain status examples/launchpad-saas
uv run swain scan examples/launchpad-saas --output markdown --mock
uv run pytest -q
uv run ruff check scripts src tests examples
uv run mypy src/descry
```

## Fresh Checkout Gate

Use a temp clone before a public release:

```bash
tmp=$(mktemp -d)
git clone /path/to/swain "$tmp/swain"
cd "$tmp/swain"
uv sync
uv run swain doctor examples/launchpad-saas --no-probe-workers
uv run swain status examples/launchpad-saas
uv run swain scan examples/launchpad-saas --output markdown --mock
uv run pytest -q
uv run ruff check scripts src tests examples
uv run mypy src/descry
```

For a hosted repository, replace `/path/to/swain` with the GitHub clone URL.
