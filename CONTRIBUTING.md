# Contributing

Thanks for helping make Swain useful for builders shipping real apps.

## Development Setup

```bash
git clone https://github.com/Descry-Technologies/Swain.git
cd swain
uv sync
uv run swain doctor examples/launchpad-saas --no-probe-workers
```

Use the intentionally vulnerable public demo for repeatable local checks:

```bash
uv run swain status examples/launchpad-saas
uv run swain scan examples/launchpad-saas --output markdown --mock
```

## Quality Gates

Run these before opening a PR:

```bash
uv run ruff check scripts src tests examples
uv run pytest -q
uv build --wheel
```

Then inspect the newest wheel:

```bash
uv run python - <<'PY'
from pathlib import Path
import zipfile

wheel = max(Path("dist").glob("*.whl"), key=lambda path: path.stat().st_mtime)
names = zipfile.ZipFile(wheel).namelist()

assert any(name.startswith("playbooks/") for name in names)
assert any(name.startswith("schemas/") for name in names)
assert not any("__pycache__" in name or name.endswith(".pyc") for name in names)
print(wheel)
PY
```

## Scope

Good contributions usually improve one of these paths:

- source install and first-run reliability
- launch-risk playbooks for auth, billing, uploads, tenant isolation, secrets,
  SQL, and XSS
- clearer worker failure messages for Claude/Codex quota or auth problems
- safer local handling of files, memory, and patch drafts
- tests around public demo behavior and release gates

Keep changes focused. Avoid broad rewrites unless they are needed to remove a
real blocker.

## Security Work

Do not include customer code, real secrets, private repository names, local
machine paths, or private screenshots in issues, PRs, docs, fixtures, or demo
assets. Use `examples/launchpad-saas` for public reproduction cases.

Security vulnerabilities in Swain itself should be reported through
[SECURITY.md](SECURITY.md), not public issues.
