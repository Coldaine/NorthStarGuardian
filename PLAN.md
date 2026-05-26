# Chronograph Stewardship Plan

Chronograph is the history-backed steward for agent and tool configuration. Its purpose is not read-only history. Its purpose is to make Claude, Codex, Gemini, OpenCode, and adjacent configuration durable, understandable, and maintainable over time.

Chronograph answers four questions:

- What is the current configuration?
- What changed, when, and why did it matter?
- Which changes should become durable policy?
- Which safe changes should be applied back to live config?

Chronograph does not blindly sync. It applies audited, reversible stewardship actions when history and diffs justify the change.

## Pipeline

Stages after memory curation:

- `07_recommend_actions`: turns curated diffs into stewardship actions.
- `08_plan_apply`: creates an apply plan with target paths, before/after diffs, risk level, backup path, and rollback command.
- `09_apply`: applies only approved actions or high-confidence allowlisted actions.

Chronograph-owned artifacts live under `.github/guardian/chronograph/`:

- `diffs.json`
- `recommendations.json`
- `apply-plan.json`
- `apply-results.json`
- `audit.jsonl`
- `backups/`

## Action Classes

- `observe`: snapshot or report only.
- `propose`: write recommendation files inside Chronograph.
- `promote`: update durable policy or config artifacts.
- `repair`: fix live config drift or missing includes.
- `retire`: disable or remove stale config only when explicitly safe.

## Write Authority

Chronograph may write its own repo outputs. It may also write allowlisted live tool roots such as `.claude`, `.codex`, `.gemini`, and OpenCode config. Every live write must create a timestamped backup and append an audit entry.

Allowed live-write categories:

- instruction files
- settings files
- skill, agent, and rule files
- hook config
- MCP definitions with environment values stripped
- durable memory indexes

Forbidden categories:

- credentials
- auth files
- tokens
- env values
- transcripts
- session bodies
- caches
- SQLite state
- histories
- generated logs

Destructive changes require explicit approval. Additive and reversible high-confidence changes may auto-apply when they match known-safe operations such as adding a missing `@RTK.md` include, normalizing known-safe settings, adding Chronograph metadata markers, or promoting stable memory with no conflicting entry.

## Audit Requirements

Each applied action records:

- target file
- old hash
- new hash
- risk level
- backup path
- rollback command
- reason linked to the diff or narrative that triggered it

Failed applies restore from backup when possible and leave a recovery record in the audit log.
