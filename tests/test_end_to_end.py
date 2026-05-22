"""End-to-end smoke test: analyze_diff → run_interview → assign_saga →
update_saga → write_journal_entry → render_dashboard against a real
MemoryStore (tmp_path git repo + bare local remote) with a mocked LLM client.
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


def _git(args: list[str], cwd: Path) -> str:
    result = subprocess.run(
        ["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True,
    )
    return result.stdout.strip()


def _make_repo_with_remote(tmp_path: Path) -> tuple[Path, Path]:
    """Working repo wired to a local bare remote so commit_and_push succeeds."""
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


# 2 context + 1 removed + 2 added → @@ -1,3 +1,4 @@

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


def _llm_response(text: str) -> MagicMock:
    """Mock anthropic response whose .content[0].text == text."""
    block = MagicMock()
    block.text = text
    resp = MagicMock()
    resp.content = [block]
    return resp


def _build_mock_client(principle_ids: list[str], verdict: str = "aligned") -> MagicMock:
    """Mock anthropic client driving the 5 LLM calls of run_interview + assign_saga.

    `verdict` controls what evaluate_alignment returns for the (one) relevant
    principle: "aligned", "drift", or "ambiguous".
    """
    intent_json = json.dumps({
        "one_line": "Refactored the analyze module.",
        "paragraph": "The PR refactored the analyze module by swapping helpers.",
    })
    alignment_json = json.dumps([
        {
            "principle_id": pid,
            "relevant": (i == 0),
            "verdict": verdict if i == 0 else None,
            "reasoning": f"Verdict reasoning for {verdict}." if i == 0 else None,
            "citations": ["guardian/analyze.py:2"] if i == 0 else [],
        }
        for i, pid in enumerate(principle_ids)
    ])
    chronicle_prose = f"PR #42 was assessed as {verdict}."

    client = MagicMock()
    client.messages.create.side_effect = [
        _llm_response(intent_json),
        _llm_response(alignment_json),
        _llm_response("[]"),
        _llm_response(chronicle_prose),
        _llm_response("CREATE: New Saga"),
    ]
    return client


@pytest.fixture()
def repo_and_store(tmp_path: Path) -> tuple[Path, MemoryStore]:
    """Real git repo with a bare remote and a seeded guardian-memory branch."""
    repo, _bare = _make_repo_with_remote(tmp_path)
    store = MemoryStore(repo)
    store.ensure_initialized()

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
    store.commit_and_push("chore: seed constitution for E2E test", push=True)

    return repo, store


@pytest.mark.parametrize("verdict", ["aligned", "ambiguous", "drift"])
def test_full_pr_interview_cycle(
    repo_and_store: tuple[Path, MemoryStore], verdict: str,
) -> None:
    from guardian.constitution import read_constitution

    _repo, store = repo_and_store
    diff_analysis = analyze_diff(SAMPLE_DIFF, PR_META)
    assert diff_analysis.pr_number == 42
    assert len(diff_analysis.files) == 1

    constitution = read_constitution(store)
    principle_ids = [p.id for p in constitution.principles]
    assert len(principle_ids) == 5

    client = _build_mock_client(principle_ids, verdict=verdict)

    report = run_interview(
        diff_analysis, constitution, client=client, model="claude-test-mock", pr_meta=PR_META,
    )
    assert report.pr_number == 42
    assert report.overall_verdict.value == verdict
    assert report.chronicle_paragraph
    assert report.intent.one_line
    assert client.messages.create.call_count == 4

    saga = assign_saga(
        store, report.intent, existing_sagas=[], client=client, model="claude-test-mock",
    )
    assert client.messages.create.call_count == 5
    assert saga.id
    assert saga.name == "New Saga"

    saga = update_saga(store, saga, report.pr_number)
    assert report.pr_number in saga.pr_numbers

    report = report.model_copy(update={"saga_id": saga.id})
    entry = write_journal_entry(store, report, saga)
    assert entry.pr_number == 42
    assert entry.saga_id == saga.id

    html = render_dashboard(store, constitution)
    assert html

    journal_files = store.list("journal/")
    assert journal_files, "no journal files materialised"
    raw_journal = store.read(journal_files[0])
    parts = raw_journal.split("---", 2)
    assert len(parts) == 3, f"missing YAML frontmatter delimiters: {raw_journal[:200]}"
    fm: dict[str, Any] = {}
    for line in parts[1].strip().splitlines():
        if ":" in line:
            key, _, val = line.partition(":")
            fm[key.strip()] = val.strip()
    for expected in ("pr_number", "verdict", "saga_id", "timestamp"):
        assert expected in fm, f"frontmatter missing {expected}: {fm}"
    assert int(fm["pr_number"]) == 42

    assert store.exists("sagas/_index.json")
    saga_index = store.read_json("sagas/_index.json")
    assert saga.id in [s["id"] for s in saga_index["sagas"]]

    assert store.exists("dashboard.html")
    dashboard_content = store.read("dashboard.html")
    assert "cdn.jsdelivr.net" in dashboard_content
    for directive in ("gantt", "gitGraph", "quadrantChart", "mindmap"):
        assert directive in dashboard_content, f"chart directive {directive!r} missing"
