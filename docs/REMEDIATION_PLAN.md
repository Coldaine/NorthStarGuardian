# NorthStarGuardian — Audit Findings & Remediation Plan

> **Status:** Partial implementation in progress. See completed items below.

---

## CRITICAL ISSUE: LLM Provider — Replace Anthropic SDK with OpenAI Responses API

**Discovered:** 2026-05-22  
**Severity:** Critical  
**Area:** `guardian/analyze.py`, `guardian/chronicle.py`, `guardian/cli.py`, `pyproject.toml`

### The Problem

The entire codebase is hardwired to the Anthropic Python SDK:

- **`guardian/analyze.py:226-245`** — `_call_llm()` directly calls `client.messages.create()` with Anthropic-specific kwargs (`model`, `system`, `max_tokens`, `messages`).
- **`guardian/cli.py:47-54`** — `_make_anthropic_client()` constructs `anthropic.Anthropic(api_key=...)` explicitly.
- **`guardian/cli.py:214-219`** and throughout — passes an `Anthropic` client instance as `client=client` to every LLM function.
- **`guardian/chronicle.py:284`** — `assign_saga()` takes `client: anthropic.Anthropic` in the type signature.
- **`pyproject.toml:13`** — `anthropic>=0.40.0` is a hard dependency.

This means:
- You need an `ANTHROPIC_API_KEY` secret (currently; swapping to `OPENAI_API_KEY` is the migration goal)
- The `system` prompt parameter is Anthropic-specific (OpenAI uses a top-level `instructions` field or `role: "developer"`/`role: "system"` in the input array in the Responses API — check the latest API docs for the current canonical shape)
- The `messages.create()` API is Anthropic-specific (OpenAI uses `client.responses.create()` in the Responses API or `client.chat.completions.create()` in the Chat Completions API — verify compatibility with the current API version)
- The model names (`claude-sonnet-4-6`, `claude-opus-4-7`) are Anthropic models — verify the latest official model IDs before migrating

### What Needs to Change

1. **Abstract the LLM boundary** — Define a `LLMClient` protocol/interface that both Anthropic and OpenAI backends can implement. The rest of the code should depend on the protocol, not on `anthropic.Anthropic`.
2. **Add an OpenAI Responses API backend** — Implement the protocol using `openai.responses.create()` or `openai.chat.completions.create()`.
3. **Keep the Anthropic backend as optional** — or remove it entirely based on preference.
4. **Update model config defaults** from `claude-sonnet-4-6` to the corresponding OpenAI model (e.g., `gpt-4o` or whatever the Responses API uses).
5. **Update environment variable** from `ANTHROPIC_API_KEY` to `OPENAI_API_KEY` (or support both).
6. **Update all 4 call sites** in `analyze.py` (`evaluate_alignment`, `detect_anti_patterns`, `assess_intent`, `_draft_chronicle`) and `chronicle.py` (`assign_saga`) to use the abstract interface.
7. **Update CI workflows** — `guardian.yml` and `guardian-debt.yml` reference `ANTHROPIC_API_KEY`.

### Research Context

From web research (May 2026):
- Anthropic SDK is at v0.104.0 with several recent deprecations
- The `anthropic` SDK is stable but the entire SDK dependency could be swapped for `openai`
- OpenAI's Responses API (`client.responses.create()`) is the current recommended API (replaces older assistants API patterns)
- Both SDKs use similar `client.*.create()` patterns, making an abstraction feasible

### Suggested Approach

```
LLMClient (Protocol in guardian/models.py)
  ├── AnthropicBackend(api_key)     # optional, keep for compatibility
  └── OpenAIBackend(api_key)        # new default
```

Each backend wraps the raw SDK and exposes a single `generate(prompt: str, system: str, model: str) -> str` method. The rest of the code never imports `anthropic` or `openai` directly.

---

## Findings Summary

### Category A: Infrastructure / Maintainability

| # | Issue | Severity | Notes | Status |
|---|-------|----------|-------|--------|
| A1 | 5 duplicate FakeStore implementations across test files | High | DRY violation; `test_chronicle.py`, `test_dashboard.py`, `test_governance.py`, `test_examples.py` all define their own inline FakeStore instead of importing from `conftest.py` | ✅ RESOLVED — Consolidated into `tests/conftest.py` with `__enter__`/`__exit__` |
| A2 | Private functions accessed from other modules (`chronicle._load_saga_index`) | Medium | `cli.py` and `dashboard.py` access `chronicle._load_saga_index` and `_saga_from_index_entry` which are conventionally private | ✅ RESOLVED — Promoted to public `load_saga_index`/`saga_from_index_entry` with backward-compat aliases |
| A3 | Dead code: `render_constitution_template` | Low | Defined at `constitution.py:345` but never called anywhere | ✅ RESOLVED — Removed |
| A4 | Near-duplicate functions: `assess_intent` / `assess_intent_with_constitution` | Medium | 58 lines of nearly identical code; only difference is constitution parameter | ✅ RESOLVED — Merged into `assess_intent(constitution=...)` |
| A5 | Template path/env config is duplicated | Low | `_TEMPLATE_DIR`/`_TEMPLATES_DIR` defined separately in `analyze.py`, `chronicle.py`, `dashboard.py`, `constitution.py` | |
| A6 | `write()` method's `message` parameter silently dropped | Low | Documented as "accepted but ignored" | |

### Category B: Production Bugs

| # | Issue | Severity | Notes |
|---|-------|----------|-------|
| B1 | `log_drift()` is never called from the interview pipeline | **Critical** | `governance.py:log_drift` is defined but no code in `cli.py:interview` or `run_interview` calls it. The drift ledger is never populated in production. |
| B2 | `grant_variance()` is never called from the interview pipeline | **Critical** | Variance tags are parsed from PR bodies in `assess_intent` and stored in `IntentSummary.declared_variances`, but never acted upon. No debt timers are ever created. |
| B3 | `suggestions` is always empty in `InterviewReport` | Medium | `run_interview` sets `suggestions=[]` (line 726). The LLM is never asked to generate suggestions. |
| B4 | `saga_id` is always `None` from `run_interview` | Medium | Saga assignment happens *after* `run_interview` returns, in `cli.py`. The report is created without a saga reference. |

### Category C: Missing Tests

| # | Issue | Severity | Notes |
|---|-------|----------|-------|
| C1 | `guardian/github_io.py` has zero dedicated tests | **High** | `GitHubContext.from_env`, `post_pr_comment`, `get_pr_diff`, `get_pr_meta` are all untested |
| C2 | CLI handler functions untested | **High** | `_handle_init_guardian`, `_handle_re_anchor`, `_handle_amend`, `_handle_chronicle`, `_handle_dashboard`, `_handle_status`, `sweep_debt`, `init_local` — all untested |
| C3 | No tests for `_call_llm` edge cases | Medium | Missing tests for: no text content block, multiple content blocks |
| C4 | `analyze_diff` edge cases untested | Medium | Renamed files, binary files (no patch), empty diff, files with special characters |
| C5 | `_parse_variance_tags` edge cases untested | Low | Em-dash separators, embedded variance tags in code blocks, case-insensitive matching |

### Category D: Test Philosophy

| # | Issue | Severity | Notes |
|---|-------|----------|-------|
| D1 | Heavy `MagicMock` usage for LLM | Medium | `test_analyze.py` (708 lines) and `test_chronicle.py` (482 lines) use `MagicMock` extensively. Tests verify mock call patterns rather than real data flow. |
| D2 | `run_interview` tests verify `call_count == 4` | Medium | Brittle assertion — depends on implementation detail of how many LLM calls are made |
| D3 | No `FakeLLMClient` pattern | Medium | A dict-based fake that maps prompt patterns to canned responses would eliminate all MagicMock usage |

### Category E: Architectural

| # | Issue | Severity | Notes |
|---|-------|----------|-------|
| E1 | LLM provider hardwired to Anthropic | **Critical** | See critical issue above |
| E2 | `except Exception: pass` in 4 places | Medium | `cli.py:42`, `memory.py:98/120/178`, `dashboard.py:343` — silently swallow errors |
| E3 | No diff size validation before LLM call | Medium | A 10,000-line diff would produce a massive prompt, potentially hitting token limits |
| E4 | Race condition in worktree-based memory | Low | Two concurrent PRs share the same worktree path; no locking |
| E5 | `generate_quadrant` jitter creates banding | Low | `pr_number % 7` means PRs 7, 14, 21, etc. get identical jitter |
