# Demo Script

This demo is for a solo builder evaluating Swain before shipping a SaaS app.
Keep the tone direct: Swain is a local security lead, not a compliance dashboard.

## Setup

Use `examples/launchpad-saas` for public screenshots and recordings. It is a
small intentionally vulnerable React + FastAPI SaaS with auth, billing, uploads,
tenant data, SQL, and XSS risk. Release assets should use only this public demo.

```bash
curl -fsSL https://raw.githubusercontent.com/Descry-Technologies/Swain/main/install.sh | sh
cd /path/to/your/repo
swain
swain demo
```

Say: "The normal path is install, cd into your repo, type `swain`, and answer
setup. The demo path stays offline so nobody spends quota while evaluating."

## Flow

1. Start with preflight.

   ```bash
   swain demo
   ```

   Say: "Before I trust an AI scan, I want to know whether its workers,
   playbooks, and local repo state are healthy."

   Point out:
   - Claude/Codex status and quota/auth diagnostics
   - applicable playbook count
   - package hygiene checks
   - clear next steps instead of raw stack traces

2. Open the agent.

   ```bash
   swain demo --tui
   ```

   Say: "This opens as a conversation. It names the repo, explains the first
   scan, and does not write `.swain/` until I choose to scan or initialize."

3. Ask a vibecoder question.

   ```text
   are we ready to ship?
   ```

   Expected behavior: Swain answers locally with the launch-risk bar: auth,
   payments, uploads, secrets, and tenant/data access.

4. Run a scan.

   ```text
   /scan
   ```

   Say: "The deterministic checks run first, then the worker pool routes
   Claude/Codex to focused playbooks. The scan runs in isolated copies of the
   selected files, so it does not write to the app."

5. Show actionability.

   For any finding, point at:
   - short finding ID
   - file and line
   - impact and exploitability
   - confidence
   - next action

   ```text
   /fix <id>
   /feedback <id> fp
   ```

   Say: "`/fix` asks Codex for a reviewable diff. `/feedback` teaches Swain
   this repo's conventions so repeated false positives decay."

## If Claude Is Out Of Quota

Run:

```bash
swain doctor /path/to/app
```

Expected behavior: Swain reports the Claude quota/auth issue and keeps Codex as
fallback when possible. The important point is graceful degradation, not a silent
failure.

## Close

End with the core promise:

> "Swain is the security lead for people shipping fast. It watches the risky
> product surfaces, tells you what matters, drafts fixes, and learns when it is
> wrong."
