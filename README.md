# NorthStarGuardian

An advisory GitHub Action that watches a repository drift from its declared identity.

The Guardian runs on every pull request. It does not block merges, does not modify source code, and does not act as a CI gate. It reads a project-authored Constitution — identity statement, ranked principles, approved architecture, anti-patterns — and writes a structured **interview** of the PR back as a comment: does this change reinforce or dilute the project's identity? It chronicles every PR into a journal grouped into named sagas, and maintains a Mermaid dashboard. All Guardian state lives on a `guardian-memory` orphan branch that shares no history with `main`.

See [`docs/SPEC.md`](docs/SPEC.md) for the full semantic specification and [`docs/ADDENDUM.md`](docs/ADDENDUM.md) for in-flight design questions.

Chronograph is Guardian's history-backed configuration steward. It records tool and agent configuration evidence, explains what changed over time, recommends durable policy improvements, plans reversible apply actions, and may apply tightly scoped live configuration repairs. Chronograph does not blindly sync machines or rewrite arbitrary files; it applies audited, allowlisted, reversible stewardship actions with backups and an append-only audit trail.

## Status

Pre-alpha. End-to-end test passing against a synthetic PR fixture. Not yet proven against a real-world pull request — that milestone is next. The core pipeline (diff analysis → Claude interview → PR comment → memory commit → dashboard render) runs without error. No production installs yet.

## Quickstart

1. **Copy the workflow** — copy `examples/consumer-workflow.yml` into `.github/workflows/guardian.yml` in your target repo and commit it to `main`.

2. **Add the secret** — in your target repo go to Settings → Secrets and variables → Actions and add `ANTHROPIC_API_KEY` as a repository secret.

3. **Author the Constitution** — comment `/init-guardian` on any open PR or issue; the Guardian will reply with setup instructions. Then, from a local checkout of the target repo, run `guardian init-local` to author the Constitution interactively (CI has no TTY, so the guided interview must run locally).

4. *(Optional)* **Enable the dashboard** — in your target repo go to Settings → Pages and point GitHub Pages at the `guardian-memory` branch. The dashboard becomes publicly viewable at `https://<org>.github.io/<repo>/dashboard.html`.

## What it does on every PR

- Posts an **Interview Report** as a PR comment: alignment summary, per-principle verdict (relevant ones only — no wall of checkmarks), saga assignment, concrete suggestions, and a chronicle paragraph.
- Regenerates `dashboard.html` on the `guardian-memory` branch with four Mermaid charts: Saga Timeline (Gantt), Branch Topology (GitGraph), Strategic Quadrant (value vs. debt), and Principle Map (Mindmap linking changes to constitutional principles).
- Appends a journal entry to the orphan branch and updates saga state.
- Records any drift events or granted variances in the drift ledger and debt timers.

Nothing is written to `main`. If the workflow fails, `main` is unaffected.

## Examples

- [`examples/sample-constitution.md`](examples/sample-constitution.md) — a complete Constitution for a fictional LLM pipeline project.
- [`examples/sample-dashboard.html`](examples/sample-dashboard.html) — a rendered dashboard showing all four chart types populated with sample data.

## Slash commands

| Command | Purpose |
|---|---|
| `/init-guardian` | First-time setup: guided interview produces `constitution.md` on the `guardian-memory` branch |
| `/re-anchor` | Refresh or refocus the Constitution; shows current values and asks what changed |
| `/amend [principle]` | Modify a specific tenet; accepts replacement text + rationale; logs the amendment |
| `/chronicle` | View project history — full, by-saga, by-date-range, or drift-only |
| `/dashboard` | Trigger a full dashboard regeneration and post the Pages link |
| `/status` | Quick health check: active sagas, open debt timers, last interview, drift trend |

## Chronograph Stewardship

Chronograph extends Guardian from passive history into active configuration care for agent and tool roots such as `.claude`, `.codex`, `.gemini`, and OpenCode config. Its local pipeline is:

| Stage | Command | Purpose |
|---|---|---|
| `07_recommend_actions` | `guardian chronograph-recommend-actions` | Convert curated config diffs into concrete stewardship actions |
| `08_plan_apply` | `guardian chronograph-plan-apply` | Build an apply plan with target paths, before/after diffs, risk, backup paths, and rollback commands |
| `09_apply` | `guardian chronograph-apply` | Apply approved or high-confidence allowlisted actions and append audit records |

Action classes are `observe`, `propose`, `promote`, `repair`, and `retire`. Live writes are allowlist-only and every applied write records the target file, old and new hashes, risk level, backup path, rollback command, and historical reason. Destructive actions are never auto-applied.

## Configuration

Runtime configuration lives at `meta/guardian-config.json` on the `guardian-memory` branch (created by `/init-guardian` with defaults). Edit it directly on that branch to change behavior.

**`enable_blocking_escalation` — defaults to `false`.**
The spec (§5) defines three escalation levels for unresolved variance debt, the third of which blocks future PRs touching the same area. This flag is off by default because the North Star anti-goal — "the Guardian must never become an authority" — supersedes that escalation. The debt machinery still runs and records expired timers; only the merge-block side effect is gated. Operators can opt in per repo by setting this to `true`.

Other fields:

| Field | Default | Description |
|---|---|---|
| `memory_branch` | `"guardian-memory"` | Name of the orphan branch where all Guardian state is stored |
| `anthropic_model_analysis` | `"claude-sonnet-4-6"` | Model used for PR diff analysis and interview generation |
| `anthropic_model_initialization` | `"claude-opus-4-7"` | Model used for Constitution authoring (`/init-guardian`, `/re-anchor`) |
| `variance_default_days` | `7` | Default debt-timer duration when a `[VARIANCE]` tag omits an expiry |
| `pages_url` | `null` | GitHub Pages URL for the dashboard; posted in comment footers when set |

## Layout

```
guardian/
  constitution.py   # read / init / amend the Constitution
  memory.py         # orphan-branch git I/O
  analyze.py        # diff analysis + Claude-backed intent/alignment/anti-pattern checks
  chronicle.py      # journal entries + saga registry
  governance.py     # drift ledger, variance protocol, debt timers
  dashboard.py      # Mermaid charts -> self-contained dashboard.html
  cli.py            # entry point for CI and slash commands
  templates/        # constitution skeleton, dashboard HTML, prompts
.github/workflows/
  guardian.yml      # PR interview + comment-triggered slash commands
  guardian-debt.yml # scheduled debt-timer sweeps
tests/
docs/SPEC.md
docs/ADDENDUM.md
```

## Anti-goals

The Guardian must never become noise. It must never become an authority. It must never take on the work it observes. See the North Star in [`docs/SPEC.md`](docs/SPEC.md).

## Local development

```
python -m venv .venv
. .venv/Scripts/Activate.ps1
pip install -e ".[dev]"
guardian --help
```
