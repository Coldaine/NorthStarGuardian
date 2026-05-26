# Repository Guardian — Working Addendum

This document stages proposed changes, open questions, and design work that is not yet locked into the main specification (`repository-guardian-spec.md`). It exists so the spec is not rewritten on every iteration. Items here graduate into the spec once settled.

---

## A1. Tool Inventory Review (staging)

The spec lists 18 tools across 6 categories. Some are grounded in what was asked for; some are assistant-invented and may be over-built. Below is an honest read, grouped by how speculative each is. Nothing changes in the spec until you mark a verdict.

Verdict options: KEEP / REPLACE / CUT / MERGE.

### Grounded — recommend KEEP

| Tool(s) | Category | Why it is grounded | Verdict |
|---|---|---|---|
| `read_memory`, `write_memory`, `list_memory` | Memory I/O | Repo-native `.github/guardian/` state needs a small read/write/list boundary | |
| `read_north_star`, `initialize_north_star` | North Star | You asked for tenets and a guided setup command | |
| `analyze_diff`, `evaluate_alignment`, `assess_intent` | Analysis | Core to checking a PR against the North Star | |
| `write_journal_entry`, `read_chronicle` | Chronicle | You asked for a journal and a way to read project history | |
| `log_drift` | Governance | Recording drift is the core observational act | |

### Possibly redundant — recommend MERGE or simplify

| Tool(s) | Category | The concern | Verdict |
|---|---|---|---|
| `amend_north_star` | North Star | May just be a behavior of the `/amend` command, not a standalone tool | |
| `detect_anti_patterns` | Analysis | Likely a sub-function of `evaluate_alignment`, not separate | |

### Assistant-invented — flagged for your decision

| Tool(s) | Category | Honest read | Verdict |
|---|---|---|---|
| `assign_saga`, `update_saga` | Chronicle | "Saga" is my term. The idea of grouping related PRs may be worth keeping, but the name and the two-tool split are mine. Invented but harmless | |
| `grant_variance`, `check_debt_timers`, `escalate_debt` | Governance | The variance and debt-timer machinery is entirely mine. `escalate_debt` can end in a merge block, which directly contradicts the North Star anti-goal of never being an authority. This is the strongest candidate for replacement | |

**My recommendation, not a decision:** the variance and debt-timer apparatus is the most over-built and the most off-North-Star piece in the spec. It deserves either a much lighter replacement or a cut. The saga tools are invented but benign. Everything else is grounded.

---

## A2. Dashboard Visual Design (open)

You said you like the visualization tools but wish their design came from somewhere proven rather than being invented here.

Recorded as `[OPEN]`: the dashboard's visual design is deferred. The tools (which charts exist, what data they consume) can stay in the spec; the look, layout, and aesthetic are to be sourced from an existing design you supply or point to, not specified from scratch in this document.

Action needed from you: name the source design, or the artifact whose aesthetic the dashboard should inherit.

---

## A3. Multi-Axis Tagging System (proposal)

You asked whether one tag system is enough, and observed that tags are effective at drawing an agent's eye. The answer is that one system is not enough, and the fix is not more values on one axis but several small tag systems on different axes, each visually distinct.

The spec currently uses a single axis: provenance, `[OWNER]` / `[INFERRED]` / `[OPEN]`.

### The proposal

Each axis is its own closed vocabulary with its own delimiter shape. The delimiter shape carries the axis; the word inside carries the value; a co-located legend defines both. A reader or a parser can tell which axis a tag belongs to before reading the word.

| Axis | Question it answers | Delimiter | Vocabulary |
|---|---|---|---|
| Provenance | Where did this come from? | `[ ]` square | `[OWNER]` `[INFERRED]` `[OPEN]` |
| Lifecycle | How settled is this? | `{ }` curly | `{LOCKED}` `{DRAFT}` `{CONTESTED}` |
| Priority | How load-bearing is this? | `« »` guillemet | `«CORE»` `«SECONDARY»` `«OPTIONAL»` |

### Why distinct delimiters

If provenance and priority both used square brackets, the eye and the parser would have to read the word to know which axis a tag belongs to. Distinct shapes make the axis pre-attentive: you see `{ }` and you know it is lifecycle without reading further. Tags then compose on one line without collision. A single requirement can carry `[OWNER] {LOCKED} «CORE»` and all three are legible at once, each on its own channel.

### Why this is the disciplined version of emoji

Emoji fails as a signaling channel because both the symbol and its meaning are unbounded and context-dependent. Here the delimiter set is closed and shape-coded, each vocabulary is closed, and a legend pins every term. Three small bounded systems, not one large ambiguous one.

### Open for your input

The three axes above are a starting set. Confidence and volatility are candidate fourth and fifth axes, though confidence overlaps with provenance, since `[INFERRED]` already implies lower confidence. Recommend starting with three and adding only if a real need appears.

Decision needed from you: approve the three-axis set, adjust the vocabularies, or change the delimiter shapes. Once settled, the spec can be retrofitted with all three.
