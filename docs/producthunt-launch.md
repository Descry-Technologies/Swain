# Product Hunt Launch

## Positioning

Name: Swain

Tagline: A local AI security lead for vibe coders shipping SaaS fast

Short description:

```text
Swain runs on your Claude/Codex CLIs, scans launch-risk surfaces, tells you what to fix first, and drafts reviewable patches.
```

Categories:

- Developer Tools
- Security
- AI

Primary CTA: https://github.com/Descry-Technologies/Swain

Secondary CTA: README quickstart and demo assets

## Launch Story

Swain is not a generic scanner and not a SaaS dashboard. It is a local security
lead for the moment when a fast-built app is almost ready to ship and needs a
practical review of auth, billing, uploads, tenant boundaries, secrets, SQL, and
XSS.

What to emphasize:

- one-command source installer from GitHub
- `swain update` for source-based updates without PyPI
- first launch setup for Claude/Codex/hybrid mode, model selection, and scan speed
- direct API runtime is available for advanced users, but CLI subscriptions stay
  the main product path
- uses Claude/Codex CLIs builders may already pay for
- focused on practical launch risks, not broad compliance
- `status` gives a fix-first recommendation
- `fix` drafts a reviewable patch, not an auto-applied change
- `feedback` teaches false positives
- the public demo app is intentionally vulnerable and safe to show

## Gallery

Use these assets instead of a wall of terminal text:

- `docs/assets/demo/scan-flow.gif`
- `docs/assets/demo/status.svg`
- `docs/assets/demo/finding-narrative.svg`
- `docs/assets/demo/doctor.svg`
- `docs/assets/demo/tui-first-run.svg`

The status asset should show `Fix first: bee77255`.

## First Comment Draft

```text
Hey PH - I built Swain because vibe-coded apps often get to "almost ready to ship" before anyone looks closely at auth, billing, uploads, tenant boundaries, secrets, SQL, or XSS.

Swain is a local AI security lead for that moment.

It runs from your repo, uses your existing Claude/Codex CLIs, scans the risky product surfaces first, and tells you what to fix before launch. It also drafts reviewable patches and learns from false-positive feedback.

For v1, the install path is one curl command from GitHub, then `swain` inside your repo. First launch explains what Swain reads/writes and lets you choose Claude, Codex, or hybrid mode before a real scan. The public demo app is intentionally vulnerable, so you can see the full loop with `swain demo` before exposing private code.

Would love feedback from solo builders shipping real apps fast.
```

## Common Replies

Does this send code to OpenAI or Anthropic?

Swain is local-first but not air-gapped. Real scans call your local Codex and/or
Claude CLIs with selected file copies. It does not run a separate hosted Swain
service. Link: `docs/privacy-and-trust.md`.

How is this different from Semgrep or Snyk?

Swain is narrower. It focuses on launch-risk product surfaces and gives a
human fix-first review. Use Semgrep/Snyk for broader static/dependency coverage.

Can I use it without Claude?

The offline demo works with `swain demo`. Real scans need at least one usable
local model worker. If Claude is unavailable, Swain can use Codex when installed
and authenticated.

Does it auto-fix?

No. `swain fix <id>` asks Codex for a patch draft and prints a unified diff for
review.

Is it production ready?

Use it as a launch-risk review assistant, not as a replacement for tests,
professional security review, or a formal audit. The v1 installer is
source-based under the hood, so the install-to-first-finding loop stays easy to
inspect.
