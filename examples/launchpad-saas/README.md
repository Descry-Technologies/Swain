# Launchpad SaaS Demo

Launchpad is a deliberately vulnerable demo app for Swain screenshots, release
smoke checks, and public walkthroughs. It is not a real product.

The app looks like a small B2B SaaS with:

- React frontend
- FastAPI backend
- tenant accounts
- checkout and webhook billing flows
- file uploads
- user search
- HTML preview rendering

The vulnerabilities are intentional and compact so Swain has realistic launch
risk to discuss without exposing private customer code.

## Demo Commands

From the Swain repo:

```bash
uv run swain doctor examples/launchpad-saas --no-probe-workers
uv run swain status examples/launchpad-saas
```

For scan demos, copy this directory to a temp location first so scan history
does not dirty the repository:

```bash
tmp=$(mktemp -d)
cp -R examples/launchpad-saas "$tmp/launchpad-saas"
uv run swain scan "$tmp/launchpad-saas" --output markdown --mock
uv run swain scan "$tmp/launchpad-saas" --output markdown
```
