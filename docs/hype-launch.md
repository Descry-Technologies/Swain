# Hype Launch Playbook

Swain's launch should sell one simple idea:

```text
Ask your repo if it is safe to ship.
```

The audience is less-technical vibe coders and solo builders with real apps.
They do not want a security taxonomy. They want a launch decision, the first
thing to fix, and confidence that Swain will not silently edit their code.

## Product Moment

The shareable moment is `swain launch-card`.

```bash
swain demo
swain launch-card examples/launchpad-saas --out docs/assets/demo/launch-card.svg
```

Use `docs/assets/demo/launch-card.svg` as the first image in launch posts. It
shows:

- `BLOCKED` as the ship/no-ship verdict
- open findings and launch blockers
- the top finding ID
- the next review-only fix command

The product landing page lives at `docs/launch/index.html`. The Pages workflow
deploys `docs/`; after GitHub Pages is enabled for Actions, the launch URL
becomes:

```text
https://descry-technologies.github.io/Swain/launch/
```

## LinkedIn Post Set

### Post 1: Build In Public

```text
I asked my repo if it was safe to ship.

Swain blocked launch.

Not because of dependency noise or vague scanner output. It found the first
product risk that actually matters before release, ranked it, and gave me a
review-only fix command.

The interesting part: the output is a launch verdict, not a wall of findings.
```

Attach `docs/assets/demo/launch-card.svg`.

### Post 2: Demo Loop

```text
The workflow I wanted:

1. Open my app repo
2. Ask "can I ship?"
3. Get launch blockers
4. Draft the first fix
5. Keep all source edits review-only

That is Swain: a local AI security lead for vibe-coded apps.
```

Attach `docs/assets/demo/scan-flow.gif`.

### Post 3: Trust

```text
I do not want an AI security tool silently changing my app.

Swain scans locally, uses selected file copies for Claude/Codex workers, and
prints patch drafts for review. The product is intentionally conservative:
scan, rank, explain, draft - but do not apply.
```

Attach `docs/assets/demo/finding-narrative.svg`.

## Product Hunt Page

Tagline:

```text
Ask your repo if it is safe to ship
```

Description:

```text
Swain is a local AI security lead for vibe-coded apps. It scans launch-risk
surfaces, gives a ship/no-ship verdict, ranks the first fix, and drafts
review-only patches through your Claude/Codex CLIs.
```

Gallery order:

1. `docs/assets/demo/launch-card.svg`
2. `docs/assets/demo/scan-flow.gif`
3. `docs/assets/demo/status.svg`
4. `docs/assets/demo/finding-narrative.svg`
5. `docs/assets/demo/doctor.svg`
6. `docs/assets/demo/tui-first-run.svg`

Primary CTA:

```text
https://descry-technologies.github.io/Swain/launch/
```

Fallback CTA if GitHub Pages is not enabled:

```text
https://github.com/Descry-Technologies/Swain
```

Maker comment structure:

1. Why it exists: vibe-coded apps reach "almost ready" before security review.
2. What it does: local launch-risk review with a ship/no-ship verdict.
3. Why it is different: fix-first coworker flow, not a generic scanner.
4. Trust boundary: local-first, review-only patches, no silent source edits.
5. Ask: try `swain demo`, then comment with what would make you trust it.

## Launch Week Checklist

- Product page has one-command install and `swain demo` above the fold.
- First image is the launch card, not terminal output.
- Demo GIF shows question -> scan -> blocker -> first fix.
- README says exactly what gets sent to Claude/Codex workers.
- `swain doctor` output is ready for quota/auth questions.
- Maker replies avoid asking for upvotes; ask for comments and feedback.
- First 20 outreach messages ask people to try the demo, not vote.

## Product Requirements For Hype

- Default language stays non-expert: "blocked", "fix first", "review-only".
- No raw worker trace appears unless the user asks for details.
- Every launch-blocking finding needs a short ID and one next command.
- Timeout states must still produce a useful partial verdict.
- Public assets must only use `examples/launchpad-saas`.
