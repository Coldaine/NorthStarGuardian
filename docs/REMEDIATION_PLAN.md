# NorthStarGuardian — Audit Findings & Remediation Plan

> **Status:** Partial implementation in progress. See completed items below.

---

## CRITICAL ISSUE: LLM Provider Boundary — Abstract Raw SDK Usage

**Discovered:** 2026-05-22  
**Severity:** Critical  
**Area:** `guardian/analyze.py`, `guardian/chronicle.py`, `guardian/cli.py`, `pyproject.toml`

### The Problem

The first implementation mixed raw Anthropic SDK clients with an emerging fake-client test interface:

- **Resolved in this stack:** `guardian.analyze` and `guardian.chronicle` now call a shared `generate(...)` interface.
- **Resolved in this stack:** `guardian.cli` constructs an adapter instead of passing a raw provider SDK client into domain modules.
- **Still open:** the only bundled backend is Anthropic. Adding an OpenAI Responses API backend remains a future provider-expansion task, not a correctness blocker for the current adapter boundary.

This means provider-specific API details now live at the boundary. Replacing or adding providers should not require touching analysis, chronicle, governance, or dashboard logic.

### What Needs to Change

1. **Abstract the LLM boundary** — ✅ Implemented as `guardian.llm.LLMClient` plus `AnthropicLLMClient`.
2. **Update all domain call sites** — ✅ `analyze.py` and `chronicle.py` use the abstract interface.
3. **Add an OpenAI Responses API backend** — still open, optional provider expansion.
4. **Update model config defaults** if/when the default provider changes.
5. **Update environment variable support** if/when another provider is bundled.

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
| B1 | `log_drift()` is never called from the interview pipeline | **Critical** | ✅ RESOLVED — `cli.py:interview` records drift evaluations into the drift ledger. |
| B2 | `grant_variance()` is never called from the interview pipeline | **Critical** | ✅ RESOLVED — declared variance tags create idempotent debt timers during interviews. |
| B3 | `suggestions` is always empty in `InterviewReport` | Medium | `run_interview` sets `suggestions=[]` (line 726). The LLM is never asked to generate suggestions. |
| B4 | `saga_id` is always `None` from `run_interview` | Medium | Saga assignment happens *after* `run_interview` returns, in `cli.py`. The report is created without a saga reference. |

### Category C: Missing Tests

| # | Issue | Severity | Notes |
|---|-------|----------|-------|
| C1 | `guardian/github_io.py` has zero dedicated tests | **High** | ✅ RESOLVED — added tests for PR event parsing, diff reconstruction, metadata extraction, and PR comments. |
| C2 | CLI command handlers untested | **High** | NOT APPLICABLE — ongoing slash-command handlers were removed to preserve the autonomous agent-side boundary. |
| C3 | No tests for `_call_llm` edge cases | Medium | Missing tests for: no text content block, multiple content blocks |
| C4 | `analyze_diff` edge cases untested | Medium | Renamed files, binary files (no patch), empty diff, files with special characters |
| C5 | `_parse_variance_tags` edge cases untested | Low | Em-dash separators, embedded variance tags in code blocks, case-insensitive matching |

### Category D: Test Philosophy

| # | Issue | Severity | Notes |
|---|-------|----------|-------|
| D1 | Heavy `MagicMock` usage for LLM | Medium | ✅ IMPROVED — analysis, chronicle, and E2E LLM paths use `FakeLLMClient`; boundary tests still use mocks for GitHub/filesystem seams. |
| D2 | `run_interview` tests verify `call_count == 4` | Medium | Brittle assertion — depends on implementation detail of how many LLM calls are made |
| D3 | No `FakeLLMClient` pattern | Medium | ✅ RESOLVED — `tests/conftest.py` provides a queued `FakeLLMClient`. |

### Category E: Architectural

| # | Issue | Severity | Notes |
|---|-------|----------|-------|
| E1 | LLM provider hardwired to Anthropic | **Critical** | PARTIAL — domain modules depend on `LLMClient`; Anthropic remains the bundled backend. |
| E2 | `except Exception: pass` in 4 places | Medium | `cli.py:42`, `memory.py:98/120/178`, `dashboard.py:343` — silently swallow errors |
| E3 | No diff size validation before LLM call | Medium | A 10,000-line diff would produce a massive prompt, potentially hitting token limits |
| E4 | Race condition in worktree-based memory | Low | Two concurrent PRs share the same worktree path; no locking |
| E5 | `generate_quadrant` jitter creates banding | Low | `pr_number % 7` means PRs 7, 14, 21, etc. get identical jitter |
