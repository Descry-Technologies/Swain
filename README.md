# swain.

**open-source local security review. one command before you ship.**

> *the machines write the code now. swain is what watches them.*

![swain launch card](docs/assets/demo/launch-card.svg)

swain is for solo builders and small teams who have a real app almost ready to ship, but still need a plain-english launch verdict: can this ship, what blocks release, and what should be fixed first?

## quickstart

install once, then run `swain` from any terminal:

```bash
curl -fsSL https://raw.githubusercontent.com/Descry-Technologies/Swain/main/install.sh | sh
cd /path/to/your/repo
swain
```

the installer clones swain's source into `~/.swain/source`, installs the `swain` command, and keeps `uv` hidden as an implementation detail. first launch explains what swain reads and writes, then asks whether scans should use claude cli, codex cli, or hybrid mode. setup builds a local project profile without spending model quota.

update without pypi:

```bash
swain update
```

from outside the repo:

```bash
swain /path/to/your/repo
```

offline demo (no quota):

```bash
swain demo
```

export a shareable launch verdict:

```bash
swain launch-card --out swain-launch-card.svg
```

## what it catches

launch-risk surfaces a fast-moving saas is most likely to get hurt on:

- **auth** — sessions, tokens, privilege escalation
- **billing** — payment trust, webhook verification
- **uploads** — path handling, tenant boundaries
- **secrets** — hardcoded values, env handling
- **sql** — injection, parameterisation
- **xss** — innerHTML, unsafe rendering
- **tenant** — object-level auth, isolation

not a replacement for semgrep, snyk, or a professional audit. a human, fix-first review for the places that matter most before launch.

## fix first

in the interactive tui, `/scan` is the main path: swain scans the repo, builds
the ordered fix queue, then automatically saves review-only patch drafts under
`.swain/fixes/` for queued findings. `/fix <id>` is only a targeted redraft.

`swain status` summarizes the latest scan history and surfaces the first issue to fix:

```text
fix first: `bee77255` — checkout trusts client-supplied price and tenant metadata
  next: swain fix bee77255 --path examples/launchpad-saas
  wrong? swain feedback bee77255 fp --path examples/launchpad-saas
```

patch drafts do not silently apply code changes. `swain feedback <id> fp`
teaches swain when a finding is a false positive.

## launch card

`swain launch-card` turns the latest scan history into a ship/no-ship card:

- verdict: `blocked` · `review` · `ready` · `no scan yet`
- open finding count and launch-blocker count
- top issue and exact next command

designed for build-in-public updates: shows the decision, not a wall of output.

## demo

use [examples/launchpad-saas](examples/launchpad-saas) — an intentionally vulnerable react + fastapi saas app:

- [launch-card.svg](docs/assets/demo/launch-card.svg)
- [scan-flow.gif](docs/assets/demo/scan-flow.gif)
- [transcript.md](docs/assets/demo/transcript.md)

regenerate assets:

```bash
uv run python scripts/capture_demo_assets.py
```

## privacy and trust

runs locally. uses your installed `claude` and `codex` clis as model workers. stores project memory under `.swain/` in the target repo. the planner excludes `.env`, private keys, and pem files before selecting files for workers.

read [docs/privacy-and-trust.md](docs/privacy-and-trust.md) before scanning sensitive code. short version: local-first, but claude/codex clis are still third-party tools.

## memory layout

```text
.swain/
  config.yaml
  profile.yaml
  conventions.yaml
  playbooks/
  demo-history/
  .local/
    history/
    calibration.yaml
```

`config.yaml`, `profile.yaml`, `conventions.yaml`, reviewed playbooks, and `demo-history/` can be committed. `.swain/.local/` is local-only and ignored.

## contributing

start with [CONTRIBUTING.md](CONTRIBUTING.md), then:

```bash
uv run ruff check scripts src tests examples
uv run pytest -q
uv build --wheel
```

security reports go through [SECURITY.md](SECURITY.md).

## license

apache-2.0 · [descry.app](https://www.descry.app)
