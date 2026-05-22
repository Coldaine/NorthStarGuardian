# NorthStarGuardian

An advisory GitHub Action that watches a repository drift from its declared identity.

The Guardian runs on every pull request. It does not block merges, does not modify source code, and does not act as a CI gate. It reads a project-authored Constitution — identity statement, ranked principles, approved architecture, anti-patterns — and writes a structured **interview** of the PR back as a comment: does this change reinforce or dilute the project's identity? It chronicles every PR into a journal grouped into named sagas, and maintains a Mermaid dashboard. All Guardian state lives on a `guardian-memory` orphan branch that shares no history with `main`.

See [`docs/SPEC.md`](docs/SPEC.md) for the full semantic specification and [`docs/ADDENDUM.md`](docs/ADDENDUM.md) for in-flight design questions.

## Status

Pre-alpha. Skeleton in place; modules being built out.

## Install

This is a GitHub Action. Add the workflow to a target repo (see `examples/`) and run `/init-guardian` in any PR or issue comment to author the Constitution.

For local development:

```
python -m venv .venv
. .venv/Scripts/Activate.ps1
pip install -e ".[dev]"
guardian --help
```

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
