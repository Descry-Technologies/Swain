# Descry

**Autonomous AI security lead for vibe coders.**

Descry runs on your existing Claude and Codex subscriptions — no separate API bill.
It learns your codebase, generates targeted security rules, and gets smarter over time.

```bash
pip install descry          # or: uv tool install descry
descry init                 # bootstrap (< 60 seconds)
descry scan                 # first scan
descry feedback abc123 fp   # teach it what matters
```

## How it works

Descry is an orchestrator that spawns your existing `claude` and `codex` CLIs as workers.
All the heavy lifting (reading code, reasoning about vulns, generating fixes) runs against
your existing Claude Pro / Claude Code / Codex subscription — not a new API bill.

The agent's memory lives in `.descry/` inside your repo — git-reviewable, portable, no SaaS lock-in.

## Self-learning

Descry adapts to your codebase over time:

- **Conventions**: marks patterns as accepted after seeing them marked FP multiple times
- **Priorities**: infers what you care about from what you fix vs. ignore
- **Skill synthesis**: generates new targeted playbooks from observed patterns
- **Self-scheduling**: adjusts scan frequency based on where risk actually appears

## Cost

- Descry orchestrator: ~500 tokens per scan (planner reasoning)
- Heavy analysis: runs on your existing Claude/Codex subscription limits
- Net new cost: ~$0 if you already have Claude Pro or Claude Code

## `.descry/` layout

```
.descry/
  config.yaml          ← your preferences (committable)
  profile.yaml         ← auto-learned project facts (committable)
  conventions.yaml     ← accepted patterns with provenance (committable)
  playbooks/
    active/            ← promoted custom playbooks (committable)
    generated/         ← synthesized playbooks awaiting review
  .local/              ← gitignored (calibration, history, schedule)
```

## License

Apache 2.0
