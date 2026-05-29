# Demo Asset Transcript

Generated from `examples/launchpad-saas` using `scripts/capture_demo_assets.py`.
The status screenshot is seeded from checked-in fixture findings so the fix-first handoff is reproducible without live Claude/Codex quota.

## Swain Doctor

```bash
swain doctor examples/launchpad-saas --no-probe-workers
```

```text
╭──────────────╮
│ Swain Doctor │
╰─ ~─╯
┏━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Check              ┃ Status   ┃ Detail                                                ┃ Next step                                               ┃
┡━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ repo               │ ok       │ <swain>/examples/launchpad-saas │                                                         │
│ profile            │ ok       │ .swain/profile.yaml found                             │                                                         │
│ playbooks          │ ok       │ 7 applicable of 7 loaded                              │                                                         │
│ package hygiene    │ ok       │ no tracked Python bytecode                            │                                                         │
│ claude             │ ok       │ ~/.local/bin/claude found; probe skipped    │ Run `swain doctor --probe-workers` to check auth/quota. │
│ codex              │ ok       │ /usr/bin/codex found; probe skipped                   │ Run `swain doctor --probe-workers` to check auth/quota. │
└────────────────────┴──────────┴───────────────────────────────────────────────────────┴─────────────────────────────────────────────────────────┘

Ready to scan.
```

## Project Status

```bash
swain status examples/launchpad-saas
```

```text
╭──────────────╮
│ Swain Status │
╰─ ~─╯

Project: Public demo SaaS with intentional launch-risk vulnerabilities
Stack: react, fastapi, stripe
Priorities: fix auth and tenant boundary bugs before launch, verify billing webhooks and checkout trust boundaries, remove secrets and unsafe upload paths

Learned conventions: 0

Active schedule: 4 playbook(s)
  •  secrets.scan
  •  deps.osv-scan
  •  sast.xss.react
  •  sast.sql-injection

Recent runs:
  • 2026-05-29T16:45  5 finding(s)

Open findings: 5
  • CRITICAL `bee77255` Checkout trusts client-supplied price and tenant metadata (backend/app/api/v1/billing.py:15)
  • HIGH `8db1dc6b` User search query is interpolated into SQL (backend/app/db/queries.py:1)
  • HIGH `3243126a` Upload route trusts tenant_id and raw filename (backend/app/api/v1/uploads.py:10)
  • HIGH `75714357` Webhook does not verify Stripe signature (backend/app/api/v1/billing.py:27)
  • HIGH `858f678a` Preview renders unsanitized HTML (frontend/src/pages/Preview.tsx:5)

Fix first: `bee77255` — Checkout trusts client-supplied price and tenant metadata
  Next: swain fix bee77255 --path <swain>/examples/launchpad-saas
  Wrong? swain feedback bee77255 fp --path <swain>/examples/launchpad-saas
```

## Mock Scan

```bash
swain scan examples/launchpad-saas --output markdown --mock
```

```text
Running deterministic scanners...
Mission demo12345678: 7 playbook(s) to run

# Swain Security Report

**Run ID**: `demo12345678`  
**Date**: 2026-05-29 16:45 UTC


✅ No findings.
```
