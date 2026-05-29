# Release Checklist

Use this before publishing a build or recording a demo. The goal is to prove
Swain still behaves like a local security lead for a solo builder, not just
that the Python package imports.

## Automated Gates

Run from the repository root:

```bash
uv run ruff check scripts src tests examples
uv run pytest -q
uv build --wheel
```

Expected:

- Ruff exits cleanly.
- Pytest exits cleanly with no warnings.
- The wheel includes `playbooks/`, `schemas/`, and `examples/launchpad-saas/`.
- The wheel does not include Python bytecode or `__pycache__/` content.

## Launch Page

- `docs/launch/index.html` renders locally at desktop and mobile widths.
- The first viewport names Swain, explains the ship/no-ship promise, and shows
  a product image, not only terminal text.
- Open Graph and Twitter tags point at `docs/assets/demo/launch-card.png`.
- The page links to GitHub, the demo flow, and privacy/trust context.
- `docs/index.html` redirects the Pages root to `/launch/`.
- `.github/workflows/pages.yml` is present for GitHub Pages deployment from
  `docs/` after Pages is enabled for GitHub Actions in repository settings.
- If GitHub Pages is enabled for Actions, the launch URL is
  `https://descry-technologies.github.io/Swain/launch/`.

Wheel inspection:

```bash
uv run python - <<'PY'
from pathlib import Path
import zipfile

wheel = max(Path("dist").glob("*.whl"), key=lambda path: path.stat().st_mtime)
names = zipfile.ZipFile(wheel).namelist()

assert any(name.startswith("playbooks/") for name in names)
assert any(name.startswith("schemas/") for name in names)
assert any(name.startswith("examples/launchpad-saas/") for name in names)
assert not any("__pycache__" in name or name.endswith(".pyc") for name in names)
print(wheel)
PY
```

## Installer Smoke

From a checkout, verify the installer script parses and the installed command
has the public demo path:

```bash
sh -n install.sh
uv run swain demo
uv run swain update --source-dir /tmp/not-swain --check || true
```

Expected:

- `swain demo` runs doctor, status, and a mock scan without Claude/Codex quota.
- The final handoff says to open the TUI with `swain <demo-path>`.
- The installer handoff says to run `swain` inside a project, not `uv run`.
- `swain update` gives a clear managed-source message when no installer checkout
  exists.

## CLI Smoke

Use the public demo repo for release screenshots. Copy the public demo to a temp
dir so local history does not dirty the working tree:

```bash
tmp=$(mktemp -d)
cp -R examples/launchpad-saas "$tmp/launchpad-saas"
uv run swain setup "$tmp/launchpad-saas" --yes --no-profile
uv run swain doctor "$tmp/launchpad-saas" --no-probe-workers
uv run swain status "$tmp/launchpad-saas"
uv run swain scan "$tmp/launchpad-saas" --output markdown --mock
```

Expected:

- `setup` records worker mode, model defaults, and careful scan concurrency in
  `.swain/config.yaml`.
- Direct API runtime can be configured with `--codex-runtime api` or
  `--claude-runtime api`, but CLI runtime remains the default.
- `doctor` reports repo/profile/playbook/package checks and worker locations.
- `status` renders recent runs, ranks open findings, and prints a fix-first
  command when finding history exists.
- Mock scan completes and prints a markdown report.
- If any playbook fails or times out, markdown includes `Scan Warnings` and does
  not claim a clean scan.

## Real Worker Smoke

Run this when Claude/Codex quota is available:

```bash
uv run swain doctor /path/to/app
uv run swain scan /path/to/app --output markdown
```

Expected:

- Worker auth/quota failures are visible in `doctor`.
- If Claude is unavailable but Codex is available, scan falls back instead of
  crashing.
- Findings include ID, severity, confidence, file, explanation, and fix summary.
- Model workers never receive `.env`, private key, or PEM files.

## TUI Smoke

```bash
uv run swain /path/to/app
```

Expected:

- If `.swain/config.yaml` is missing, first launch runs setup before the TUI.
- First-run greeting explains the next action.
- Asking `are we ready to ship?` gives a local launch-readiness answer.
- `/scan` shows progress, finding narratives, a prioritization opinion, and a
  next action.
- The TUI side rail shows task/subagent progress instead of a silent spinner.
- `/feedback <id> fp` and `/fix <id>` are discoverable from the scan output.

## Demo Assets

Before a public release:

```bash
uv run python scripts/capture_demo_assets.py
```

This requires ImageMagick's `convert` binary for `scan-flow.gif`.

Expected assets:

- `docs/assets/demo/doctor.svg`
- `docs/assets/demo/status.svg`
- `docs/assets/demo/scan-mock.svg`
- `docs/assets/demo/scan-flow.gif`
- `docs/assets/demo/launch-card.svg`
- `docs/assets/demo/launch-card.png`
- `docs/assets/demo/tui-first-run.svg`
- `docs/assets/demo/finding-narrative.svg`
- `docs/assets/demo/transcript.md`

Keep secrets and customer code out of screenshots. Use `examples/launchpad-saas`
for public assets.

The status asset should show fixture-seeded open findings, `Fix first:
bee77255`, and a `swain fix bee77255` command so evaluators see the handoff
from scan history to action.

## Source Install Gate

Run the fresh-clone path before tagging:

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
```

For the public repository, replace `/path/to/swain` with the GitHub clone URL.

## Asset Hygiene Gate

```bash
uv run python scripts/capture_demo_assets.py
rg -n "/home/|aniol|henri" docs/assets/demo && exit 1 || true
rg -n 'Fix first: `bee77255`|swain fix bee77255' docs/assets/demo/transcript.md
```
