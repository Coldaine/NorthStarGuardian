"""End-to-end smoke test for the NorthStarGuardian PR interview cycle.

Exercises the full path:
    analyze_diff → run_interview → assign_saga → update_saga
    → write_journal_entry → render_dashboard

Uses a real MemoryStore against a tmp_path git repo (with a bare local
remote so push/fetch work) and a MagicMock Anthropic client so no real
LLM or network calls are made.

Acceptance criteria (US-001):
1. File exists at tests/test_end_to_end.py  ✓
2. Real MemoryStore with tmp_path git repo  ✓
3. run_interview driven with small diff + 4-call mock  ✓
4. assign_saga → update_saga → write_journal_entry → render_dashboard  ✓
5. journal/ file with valid YAML frontmatter, sagas/_index.json with saga,
   dashboard.html with Mermaid CDN + all 4 chart directives  ✓
6. No real LLM, no network  ✓
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from guardian.analyze import analyze_diff, run_interview
from guardian.chronicle import assign_saga, update_saga, write_journal_entry
from guardian.constitution import initialize_constitution, write_constitution
from guardian.dashboard import render_dashboard
from guardian.memory import MemoryStore

# ---------------------------------------------------------------------------
# Helpers (copied from test_memory.py to avoid cross-test coupling)
# ---------------------------------------------------------------------------


def _git(args: list[str], cwd: Path) -> str:
    """Run a git command in *cwd*, return stdout."""
    result = subprocess.run(
        ["git"] + args,
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _make_repo_with_remote(tmp_path: Path) -> tuple[Path, Path]:
    """Create a working repo wired to a local bare remote.

    Returns (working_repo, bare_remote).
    The bare remote means commit_and_push succeeds without any real origin.
    """
    bare = tmp_path / "remote.git"
    bare.mkdir()
    _git(["init", "--bare", "-b", "main"], cwd=bare)

    repo = tmp_path / "repo"
    repo.mkdir()
    _git(["init", "-b", "main"], cwd=repo)
    _git(["config", "user.email", "test@example.com"], cwd=repo)
    _git(["config", "user.name", "Test"], cwd=repo)
    (repo / "README.md").write_text("# test repo\n")
    _git(["add", "README.md"], cwd=repo)
    _git(["commit", "-m", "initial commit"], cwd=repo)
    _git(["remote", "add", "origin", str(bare)], cwd=repo)
    _git(["push", "-u", "origin", "main"], cwd=repo)
    return repo, bare


# ---------------------------------------------------------------------------
# Minimal well-formed unified diff (2 context, 1 removed, 2 added → @@ -1,3 +1,4 @@)
# ---------------------------------------------------------------------------

SAMPLE_DIFF = """\
--- a/guardian/analyze.py
+++ b/guardian/analyze.py
@@ -1,3 +1,4 @@
 # existing line
-old_code()
+new_code()
+import os
 # end
"""

PR_META: dict[str, Any] = {
    "number": 42,
    "title": "Refactor analyze module",
    "body": "Cleans up the analyze module internals.",
    "author": "alice",
    "base_sha": "abc123",
    "head_sha": "def456",
    "commit_messages": ["refactor: clean up analyze internals"],
}


# ---------------------------------------------------------------------------
# Mock LLM response builder
# ---------------------------------------------------------------------------


def _text_block(text: str) -> MagicMock:
    """Return a mock content-block with a .text attribute."""
    block = MagicMock()
    block.text = text
    return block


def _llm_response(text: str) -> MagicMock:
    """Return a mock anthropic response whose .content[0].text == text."""
    resp = MagicMock()
    resp.content = [_text_block(text)]
    return resp


def _build_mock_client(principle_ids: list[str]) -> tuple[MagicMock, list[MagicMock]]:
    """Build a MagicMock anthropic client with a side_effect list for 5 calls.

    Call order (matching run_interview orchestration + assign_saga):
      1. assess_intent          → JSON object  {one_line, paragraph}
      2. evaluate_alignment     → JSON array   [{principle_id, relevant, verdict, ...}]
      3. detect_anti_patterns   → JSON array   [] (no matches)
      4. _draft_chronicle       → plain prose  (no JSON)
      5. assign_saga            → "CREATE: New Saga"

    Returns (client, responses_list) so tests can inspect calls.
    """
    # Call 1 – assess_intent
    intent_json = json.dumps({
        "one_line": "Refactored the analyze module to improve clarity.",
        "paragraph": (
            "The PR refactored the analyze module, removing old_code() in favour of "
            "new_code() and adding an os import. The change was motivated by a desire "
            "to simplify internal logic. No architectural shift was signalled."
        ),
    })

    # Call 2 – evaluate_alignment (one entry per principle)
    alignment_json = json.dumps([
        {
            "principle_id": pid,
            "relevant": (i == 0),  # first principle is relevant
            "verdict": "aligned" if i == 0 else None,
            "reasoning": "Change stays within declared architecture." if i == 0 else None,
            "citations": ["guardian/analyze.py:2"] if i == 0 else [],
        }
        for i, pid in enumerate(principle_ids)
    ])

    # Call 3 – detect_anti_patterns (empty — no matches)
    ap_json = json.dumps([])

    # Call 4 – _draft_chronicle (plain prose, not JSON)
    chronicle_prose = (
        "PR #42 refactored the analyze module, replacing old_code() with new_code() "
        "and adding an os import. The change was assessed as aligned with the project's "
        "core architecture principle. No drift was detected."
    )

    # Call 5 – assign_saga
    saga_response = "CREATE: New Saga"

    responses = [
        _llm_response(intent_json),
        _llm_response(alignment_json),
        _llm_response(ap_json),
        _llm_response(chronicle_prose),
        _llm_response(saga_response),
    ]

    client = MagicMock()
    client.messages.create.side_effect = responses

    return client, responses


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def repo_and_store(tmp_path: Path) -> tuple[Path, MemoryStore]:
    """Set up a real git repo with a bare remote and a seeded guardian-memory branch."""
    repo, _bare = _make_repo_with_remote(tmp_path)
    store = MemoryStore(repo)
    store.ensure_initialized()

    # Seed the orphan branch with a Constitution.
    constitution = initialize_constitution(
        {
            "project_name": "TestProject",
            "identity_statement": (
                "TestProject is an LLM-powered analysis pipeline. "
                "It is not a collection of standalone scripts."
            ),
            "principles": [
                "All analysis flows through the LLM layer.",
                "Prefer functional composition over mutable state.",
                "No standalone scripts that bypass the LLM.",
                "All public functions are type-annotated.",
                "Tests mock LLM calls; no real network access in CI.",
            ],
            "approved_architecture": (
                "Python 3.11+, Pydantic v2 models, Anthropic SDK for LLM calls, "
                "Jinja2 for templating, unidiff for diff parsing."
            ),
            "anti_patterns": [
                {
                    "id": "ap1",
                    "description": "Standalone scripts that bypass the LLM layer.",
                    "example": "scripts/run_analysis.sh",
                },
            ],
        },
        actor="test-setup",
    )
    write_constitution(store, constitution, rationale="Initial constitution for E2E test")
    store.commit_and_push(
        "chore: seed constitution for E2E test",
        push=True,
    )

    return repo, store


# ---------------------------------------------------------------------------
# The smoke test
# ---------------------------------------------------------------------------


def test_full_pr_interview_cycle(repo_and_store: tuple[Path, MemoryStore]) -> None:
    """Full PR interview cycle: diff → interview → saga → journal → dashboard."""
    _repo, store = repo_and_store

    # ------------------------------------------------------------------
    # 1. Analyze diff (pure Python, no LLM)
    # ------------------------------------------------------------------
    diff_analysis = analyze_diff(SAMPLE_DIFF, PR_META)
    assert diff_analysis.pr_number == 42
    assert diff_analysis.pr_title == "Refactor analyze module"
    assert len(diff_analysis.files) == 1

    # ------------------------------------------------------------------
    # 2. Load constitution to discover principle IDs for mock building
    # ------------------------------------------------------------------
    from guardian.constitution import read_constitution
    constitution = read_constitution(store)
    principle_ids = [p.id for p in constitution.principles]
    assert len(principle_ids) == 5  # we seeded 5 principles

    # ------------------------------------------------------------------
    # 3. Build mock client (5 canned responses)
    # ------------------------------------------------------------------
    client, _responses = _build_mock_client(principle_ids)

    # ------------------------------------------------------------------
    # 4. Run interview (consumes mock calls 1–4)
    # ------------------------------------------------------------------
    report = run_interview(
        diff_analysis,
        constitution,
        client=client,
        model="claude-test-mock",
        pr_meta=PR_META,
    )

    assert report.pr_number == 42
    assert report.overall_verdict.value in {"aligned", "ambiguous", "drift"}
    assert report.chronicle_paragraph  # non-empty prose
    assert report.intent.one_line
    # Verify LLM was called exactly 4 times so far
    assert client.messages.create.call_count == 4

    # ------------------------------------------------------------------
    # 5. Assign saga (consumes mock call 5)
    # ------------------------------------------------------------------
    saga = assign_saga(
        store,
        report.intent,
        existing_sagas=[],
        client=client,
        model="claude-test-mock",
    )

    assert client.messages.create.call_count == 5
    assert saga.id  # slug was generated
    assert saga.name == "New Saga"

    # ------------------------------------------------------------------
    # 6. Update saga + update report with saga_id
    # ------------------------------------------------------------------
    saga = update_saga(store, saga, report.pr_number)
    assert report.pr_number in saga.pr_numbers

    report = report.model_copy(update={"saga_id": saga.id})

    # ------------------------------------------------------------------
    # 7. Write journal entry
    # ------------------------------------------------------------------
    entry = write_journal_entry(store, report, saga)
    assert entry.pr_number == 42
    assert entry.saga_id == saga.id

    # ------------------------------------------------------------------
    # 8. Render dashboard
    # ------------------------------------------------------------------
    html = render_dashboard(store, constitution)
    assert html  # non-empty

    # ------------------------------------------------------------------
    # 9. Assertions on persisted state
    # ------------------------------------------------------------------

    # 9a. Journal file exists with valid YAML frontmatter
    journal_files = store.list("journal/")
    assert journal_files, "No journal files found under journal/"

    journal_path = journal_files[0]
    raw_journal = store.read(journal_path)

    # Parse YAML frontmatter manually (same technique as chronicle module)
    parts = raw_journal.split("---", 2)
    assert len(parts) == 3, f"Journal file missing YAML frontmatter delimiters: {raw_journal[:200]}"

    fm: dict[str, Any] = {}
    for line in parts[1].strip().splitlines():
        if ":" in line:
            key, _, val = line.partition(":")
            fm[key.strip()] = val.strip()

    assert "pr_number" in fm, f"Frontmatter missing pr_number: {fm}"
    assert "verdict" in fm, f"Frontmatter missing verdict: {fm}"
    assert "saga_id" in fm, f"Frontmatter missing saga_id: {fm}"
    assert "timestamp" in fm, f"Frontmatter missing timestamp: {fm}"
    assert int(fm["pr_number"]) == 42

    # 9b. sagas/_index.json exists and contains the new saga
    assert store.exists("sagas/_index.json"), "sagas/_index.json does not exist"
    saga_index = store.read_json("sagas/_index.json")
    assert "sagas" in saga_index
    saga_ids = [s["id"] for s in saga_index["sagas"]]
    assert saga.id in saga_ids, f"Saga {saga.id!r} not in index: {saga_ids}"

    # 9c. dashboard.html exists, contains Mermaid CDN, and all four chart directives
    assert store.exists("dashboard.html"), "dashboard.html does not exist"
    dashboard_content = store.read("dashboard.html")
    assert "cdn.jsdelivr.net" in dashboard_content, (
        "Mermaid CDN URL not found in dashboard.html"
    )
    for directive in ("gantt", "gitGraph", "quadrantChart", "mindmap"):
        assert directive in dashboard_content, (
            f"Chart directive '{directive}' not found in dashboard.html"
        )
