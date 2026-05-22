---
pr_number: 17
saga_id: caching-layer-exploration
verdict: ambiguous
timestamp: 2026-03-04 14:22:07 UTC
---

# PR #17 — AMBIGUOUS

PR #17 introduced a `CacheBackend` abstract base class under `lumenscout/cache/` with two concrete implementations: `InMemoryCache` and `RedisCache`. The in-memory implementation stores embeddings and LLM responses in a process-local dict; the Redis implementation connects to an arbitrary URL supplied via environment variable. Both are registered behind a unified `get_cache()` factory driven by a `LUMENSCOUT_CACHE_BACKEND` environment variable.

**Alignment Summary:** The PR is internally coherent and the code is well-structured, but the `RedisCache` implementation introduces the first external service dependency in LumenScout's history. Whether this constitutes drift depends entirely on intent — the architecture has not previously addressed caching, so there is no prior ruling to apply. The Guardian cannot determine from the diff alone whether `RedisCache` is a local-only convenience (e.g. for users already running Redis on localhost) or the first step toward a hosted caching tier.

## Principle Evaluations

| Principle | Verdict | Reasoning |
|-----------|---------|-----------|
| `p2` | ambiguous | The `InMemoryCache` path is unambiguously local-first. The `RedisCache` path accepts any URL, including hosted services. If a user sets `LUMENSCOUT_CACHE_BACKEND=redis` and points it at a hosted Redis instance, user document content (embeddings) would leave the machine — a direct conflict with Principle 2. The code does not prevent or warn against this use. |
| `p1` | aligned | Both cache implementations sit below the LLM reasoning layer, caching its outputs rather than replacing them. Synthesis still flows through the LLM. |

**Saga:** Caching Layer Exploration (`caching-layer-exploration`)

## Suggestions

- If the intent is local-only Redis (e.g. a Docker container on the developer's machine), add a validator in `RedisCache.__init__` that rejects non-localhost URLs and raises a clear `LocalFirstViolationError`. This makes the constraint self-documenting and prevents future contributors from quietly wiring in a hosted instance.
- Consider adding a docstring to `CacheBackend` that explicitly states the local-first constraint: "Implementations MUST NOT transmit cached data to external services without user consent (Principle 2)." This makes the architectural boundary visible at the point where future implementors will look.
- If the team is open to a hosted Redis option behind an explicit opt-in dialog (aligned with Principle 2's "explicit opt-in confirmation"), that should be documented as an architectural decision before the interface solidifies — otherwise the `RedisCache` implementation will calcify into a pattern that's hard to revisit.
