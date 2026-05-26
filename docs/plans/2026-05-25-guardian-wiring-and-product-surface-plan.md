# Guardian Wiring and Product Surface Implementation Plan

> For agentic workers: use `superpowers:executing-plans` for implementation
> and keep this plan synchronized with the current repo-native Guardian model.

## Goal

Finish Guardian as a real automated GitHub review agent with:

- a required human-facing repo North Star at `docs/northstar.md`
- a Guardian active copy at `.github/guardian/northstar.md`
- Guardian-owned alignment history under `.github/guardian/memory/`
- optional Linear-backed policy and follow-up issue routing
- an operator dashboard and slash-command control surface

## Architecture

GitHub Actions trigger the `guardian` CLI. `guardian/cli.py` orchestrates PR
review, slash commands, and scheduled sweeps. Domain behavior remains in
`guardian/*` modules. Guardian state is tracked repo content under
`.github/guardian/`; no separate storage branch or detached checkout is part of
the current product design.

When Linear is configured, Linear may be the canonical managed policy surface.
Guardian still materializes the exact fetched document into the active copy and
writes snapshot metadata so every review can be traced to the policy body it
used.

## Current Implementation Focus

1. PR review reads the base-branch repo North Star, or fetches the configured
   Linear document.
2. Guardian persists the active copy and snapshot metadata in `.github/guardian/`.
3. Chronicle, saga, drift, debt, and dashboard records live under
   `.github/guardian/memory/`.
4. `/amend` updates local active-copy state only for repo-backed policy; for
   Linear-backed policy it creates a Linear follow-up issue.
5. GitHub workflow jobs need only repository checkout, Python setup, package
   install, and the appropriate API secrets.

## Remaining Product Work

### Task 1: Finish Interview-to-Governance Wiring

- Persist drift events during `guardian interview` when principle evaluations
  return `drift`.
- Persist declared variances from `report.intent.declared_variances` into debt
  timers during the same interview run.
- Define one shared mapping from interview verdicts and anti-pattern matches to
  governance severity.
- Add tests proving one PR interview can produce a PR comment, journal entry,
  dashboard refresh, drift ledger entries, and variance debt timers together.

### Task 2: Normalize Governance and Dashboard Contracts

- Keep one canonical JSON shape for `memory/drift-ledger.json` and
  `memory/debt-timers.json`.
- Prefer helper loaders from `guardian/governance.py` over raw dashboard reads
  where practical.
- Extend dashboard inputs to include debt-timer state where useful.
- Render dashboard tests from live governance fixtures, not chronicle-only data.

### Task 3: Improve Review Suggestions

- Generate short, optional suggestions only when they add value.
- Ground suggestions in the diff and North Star snapshot.
- Keep aligned PR comments brief.
- Test aligned, ambiguous, and drift cases.

### Task 4: Tighten Operator Commands

- Keep `/init-guardian`, `/re-anchor`, `/amend`, `/chronicle`, `/dashboard`,
  and `/status` as the operator surface.
- Make each command explicit about what it mutates and what it only reports.
- Improve `/chronicle` and `/status` so they expose real chronicle/governance
  data instead of thin summaries.
- Document Linear-backed amendment behavior clearly.

### Task 5: Mature the Dashboard

- Preserve the self-contained HTML dashboard pipeline as the shipping baseline.
- Make the first screen answer operator questions: what changed, what is
  drifting, what is overdue, and which principles are most active.
- Keep the chart generators modular so Mermaid can remain the current backend
  while the product surface evolves.

## Definition of Done

- PR review uses a pinned North Star snapshot.
- PRs cannot alter the policy used to review themselves.
- Guardian state is visible under `.github/guardian/`.
- Linear-backed policy changes are routed through Linear follow-up issues.
- The README and spec describe Guardian as an advisory GitHub review agent with
  repo-native state, optional Linear policy, operator controls, and a dashboard.
