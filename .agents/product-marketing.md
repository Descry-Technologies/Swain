# Product Marketing Context

*Last updated: 2026-05-30*

## Product Overview

**One-liner:** Swain is a local AI security lead for vibe-coded apps before launch.

**What it does:** Swain runs inside a repo, builds a project profile, scans
launch-risk surfaces, gives a ship/no-ship verdict, ranks the first fix, and
drafts review-only patches through Claude/Codex workers. It is intentionally
focused on practical release blockers, not broad compliance.

**Product category:** Developer tools, security, AI coding agents, vibe coding tools.

**Product type:** Open-source local CLI/TUI with source-based installer.

**Business model:** Free source-first release. Future packaging can add hosted
team coordination, managed workers, or paid support.

## Target Audience

**Target companies:** Solo builders, indie hackers, vibe coders, and small SaaS
teams shipping real apps quickly.

**Decision-makers:** Founder-builder, technical solo founder, early CTO, senior
full-stack engineer on a small team.

**Primary use case:** Check whether an almost-ready app has launch-blocking
security issues before posting, onboarding users, or taking payments.

**Jobs to be done:**
- Know whether the app is safe enough to launch.
- Find the first security issue that matters.
- Draft a fix without giving an AI permission to silently edit source.

**Use cases:**
- Pre-launch review for SaaS with auth, billing, uploads, tenants, SQL, or XSS risk.
- Background repo watch before a public release.
- Build-in-public launch updates using a privacy-safe launch card.

## Personas

| Persona | Cares about | Challenge | Value we promise |
|---------|-------------|-----------|------------------|
| Vibe coder founder | Shipping fast without embarrassment | Does not know which security issues matter | Plain-English ship/no-ship verdict |
| Solo technical founder | Practical fixes and low setup | No time for full audit | Fix-first ranking and review-only diffs |
| Small-team tech lead | Trust and repeatability | AI workers can be noisy or flaky | Local memory, doctor checks, partial verdicts |

## Problems & Pain Points

**Core problem:** Fast-built apps get close to launch before anyone reviews the
dangerous product surfaces.

**Why alternatives fall short:**
- Generic scanners produce too much noise and too little launch judgment.
- Security audits are too expensive or slow for early builders.
- AI coding tools can suggest fixes but do not behave like a conservative
  release reviewer.

**What it costs them:** Delayed launches, embarrassing public bugs, leaked data,
payment abuse, tenant isolation failures, and founder anxiety.

**Emotional tension:** "I built this fast, but I do not know what I missed."

## Competitive Landscape

**Direct:** AI security assistants and code review agents - often broad,
enterprise-oriented, or not local-first.

**Secondary:** Semgrep, Snyk, GitHub code scanning - useful coverage but not a
senior launch-readiness conversation.

**Indirect:** Manual review by a security friend or consultant - high quality
but slow, expensive, and hard to schedule.

## Differentiation

**Key differentiators:**
- Ship/no-ship launch verdict.
- Fix-first queue instead of raw scanner dump.
- Local-first orchestration using the user's Claude/Codex CLIs.
- Review-only patch drafts.
- Conversational TUI plus reliable slash commands.
- `swain launch-card` for social-proof launch updates.

**How we do it differently:** Swain narrows the problem to launch-risk surfaces:
auth, payments, uploads, tenant boundaries, secrets, SQL, and XSS.

**Why that's better:** Less noise, faster action, clearer trust boundaries.

**Why customers choose us:** It feels like a pragmatic senior security coworker,
not a compliance dashboard.

## Objections

| Objection | Response |
|-----------|----------|
| Does this send my code to AI providers? | Swain is local-first but not air-gapped; real scans call local Claude/Codex CLIs with selected file copies. |
| Does it auto-fix code? | No. Patch generation prints reviewable diffs only. |
| What if workers time out? | Swain reports worker diagnostics and should return partial verdicts instead of hiding failures. |

**Anti-persona:** Teams needing formal compliance evidence, full pentesting, or
air-gapped security review.

## Switching Dynamics

**Push:** Scanner noise, audit cost, uncertainty before launch.

**Pull:** One-command demo, ship/no-ship verdict, first-fix recommendation,
review-only patch drafts.

**Habit:** "I'll just ask ChatGPT/Codex to look at the code" or "I'll ship and
fix security later."

**Anxiety:** Code privacy, AI hallucinations, hidden source edits, quota failures.

## Customer Language

**How they describe the problem:**
- "I vibe-coded this and I do not know if it is safe to ship."
- "What actually blocks launch?"
- "Tell me what to fix first."

**How they describe us:**
- "A security lead in my repo."
- "The app tells me if I can ship."

**Words to use:** ship/no-ship, blocked, fix first, launch risk, review-only,
local-first, vibe-coded apps.

**Words to avoid:** autonomous hacker, compliance platform, enterprise scanner,
auto-remediation.

**Glossary:**

| Term | Meaning |
|------|---------|
| Launch blocker | A security issue worth fixing before public release |
| Launch card | Shareable 1200x630 SVG verdict generated from scan history |
| Review-only patch | A diff suggestion printed for human review, never applied silently |

## Brand Voice

**Tone:** Direct, calm, pragmatic.

**Style:** Conversational outside, structured inside.

**Personality:** Senior, blunt, careful, useful.

## Proof Points

**Metrics:** Public demo shows a reproducible fix-first flow with no live quota.

**Customers:** Not yet available.

**Testimonials:** Not yet available.

**Value themes:**

| Theme | Proof |
|-------|-------|
| No-quota evaluation | `swain demo` |
| Actionable launch review | `swain status` and `swain launch-card` |
| Trust boundary | `/fix` prints diffs and does not apply code |

## Goals

**Business goal:** Earn early adopter trust from vibe coders and solo builders.

**Conversion action:** Install from GitHub, run `swain demo`, then run Swain in a real repo.

**Current metrics:** Not yet tracked.
