"""Tests for guardian.cli — autonomous PR interview and local subcommands.

Uses Click's CliRunner so no real processes are spawned.  All external
dependencies (GitHub, Anthropic, MemoryStore) are mocked at the boundary.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from guardian.cli import cli
from guardian.models import (
    Constitution,
    DiffAnalysis,
    GuardianConfig,
    IntentSummary,
    InterviewReport,
    JournalEntry,
    Principle,
    Verdict,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_constitution() -> Constitution:
    return Constitution(
        version=1,
        project_name="TestProject",
        identity_statement="This is a test project.",
        principles=[
            Principle(id="p1", rank=1, text="Principle one"),
            Principle(id="p2", rank=2, text="Principle two"),
        ],
        approved_architecture="We use pytest for testing.",
        anti_patterns=[],
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _make_report(pr_number: int = 42) -> InterviewReport:
    return InterviewReport(
        pr_number=pr_number,
        overall_verdict=Verdict.ALIGNED,
        alignment_summary="This PR aligns with the project identity.",
        principle_evaluations=[],
        anti_pattern_matches=[],
        saga_id="test-saga",
        suggestions=["Consider adding a docstring."],
        chronicle_paragraph="PR #42 extended the test suite.",
        intent=IntentSummary(one_line="Add tests", paragraph="Adds unit tests."),
        created_at=datetime(2026, 1, 2, tzinfo=UTC),
    )


def _make_journal_entry(pr_number: int = 42) -> JournalEntry:
    return JournalEntry(
        pr_number=pr_number,
        timestamp=datetime(2026, 1, 2, tzinfo=UTC),
        saga_id="test-saga",
        verdict=Verdict.ALIGNED,
        body_markdown="PR #42 extended the test suite.",
    )


# ---------------------------------------------------------------------------
# guardian preview-dashboard
# ---------------------------------------------------------------------------


class TestPreviewDashboard:
    """preview-dashboard renders an HTML file without touching git."""

    def test_renders_html_file(self, tmp_path: Path) -> None:
        runner = CliRunner()

        constitution = _make_constitution()
        html_content = "<html><body>dashboard</body></html>"
        output_file = tmp_path / "out.html"

        mock_store = MagicMock()
        mock_store.exists.return_value = False

        import guardian.dashboard as dash_mod

        orig_render = dash_mod.render_dashboard
        dash_mod.render_dashboard = MagicMock(return_value=html_content)

        try:
            with (
                patch("guardian.cli.MemoryStore", return_value=mock_store),
                patch("guardian.cli.read_constitution", return_value=constitution),
            ):
                result = runner.invoke(
                    cli,
                    [
                        "preview-dashboard",
                        "--output", str(output_file),
                        "--repo-root", str(tmp_path),
                    ],
                )
        finally:
            dash_mod.render_dashboard = orig_render

        assert result.exit_code == 0, result.output
        # The output path should be mentioned in stdout.
        assert str(output_file.name) in result.output or "dashboard" in result.output.lower()

    def test_errors_when_no_constitution(self, tmp_path: Path) -> None:
        runner = CliRunner()

        mock_store = MagicMock()
        mock_store.exists.return_value = False

        with (
            patch("guardian.cli.MemoryStore", return_value=mock_store),
            patch("guardian.cli.read_constitution", side_effect=FileNotFoundError),
        ):
            result = runner.invoke(
                cli,
                [
                    "preview-dashboard",
                    "--output", str(tmp_path / "out.html"),
                    "--repo-root", str(tmp_path),
                ],
            )

        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# guardian interview (mocked at GitHubContext boundary)
# ---------------------------------------------------------------------------


class TestInterview:
    """interview invokes the right pipeline given a mocked event payload."""

    def _make_event_payload(self, pr_number: int = 42) -> dict[str, Any]:
        return {
            "pull_request": {
                "number": pr_number,
                "title": "Add feature",
                "body": "Adds a new feature",
                "user": {"login": "developer"},
                "base": {"sha": "abc123", "ref": "main"},
                "head": {"sha": "def456", "ref": "feature-branch"},
                "html_url": f"https://github.com/test/repo/pull/{pr_number}",
            }
        }

    def test_interview_pipeline_called(self, tmp_path: Path) -> None:
        runner = CliRunner()

        # Write a fake event payload to disk.
        payload = self._make_event_payload(42)
        event_file = tmp_path / "event.json"
        event_file.write_text(json.dumps(payload), encoding="utf-8")

        constitution = _make_constitution()
        report = _make_report(42)

        mock_store = MagicMock()
        mock_store.exists.return_value = False
        mock_store.__enter__ = MagicMock(return_value=mock_store)
        mock_store.__exit__ = MagicMock(return_value=False)
        mock_store.session = MagicMock(return_value=mock_store)
        mock_store.session.return_value.__enter__ = MagicMock(return_value=mock_store)
        mock_store.session.return_value.__exit__ = MagicMock(return_value=False)

        mock_pr = MagicMock()
        mock_pr.number = 42

        mock_ctx = MagicMock()
        mock_ctx.pr = mock_pr
        mock_ctx.event_name = "pull_request"

        mock_diff_analysis = MagicMock(spec=DiffAnalysis)

        env = {
            "GITHUB_TOKEN": "test-token",
            "GITHUB_REPOSITORY": "test/repo",
            "GITHUB_EVENT_NAME": "pull_request",
            "ANTHROPIC_API_KEY": "test-key",
        }

        with (
            patch("guardian.cli.MemoryStore", return_value=mock_store),
            patch("guardian.cli.GitHubContext") as mock_ctx_cls,
            patch("guardian.cli.get_pr_diff", return_value="diff --git ..."),
            patch("guardian.cli.get_pr_meta", return_value={"number": 42, "title": "Add feature", "body": "", "author": "dev", "base_sha": "abc", "head_sha": "def"}),
            patch("guardian.cli.read_constitution", return_value=constitution),
            patch("guardian.cli._make_anthropic_client", return_value=MagicMock()),
            patch("guardian.cli._load_config", return_value=GuardianConfig()),
            patch("guardian.cli.post_pr_comment") as mock_post,
        ):
            mock_ctx_cls.from_env.return_value = mock_ctx

            # Patch domain modules loaded inside the command.
            import guardian.analyze as analyze_mod
            import guardian.chronicle as chronicle_mod
            import guardian.dashboard as dashboard_mod

            mock_saga = MagicMock()
            mock_saga.id = "test-saga"

            with (
                patch.object(analyze_mod, "analyze_diff", return_value=mock_diff_analysis),
                patch.object(analyze_mod, "run_interview", return_value=report),
                patch.object(chronicle_mod, "load_saga_index", return_value={"sagas": []}),
                patch.object(chronicle_mod, "saga_from_index_entry", return_value=mock_saga),
                patch.object(chronicle_mod, "assign_saga", return_value=mock_saga),
                patch.object(chronicle_mod, "update_saga", return_value=mock_saga),
                patch.object(chronicle_mod, "write_journal_entry"),
                patch.object(dashboard_mod, "render_dashboard", return_value="<html/>"),
            ):
                result = runner.invoke(
                    cli,
                    ["interview", "--event-path", str(event_file), "--repo-root", str(tmp_path)],
                    env=env,
                )

        assert result.exit_code == 0, result.output
        mock_post.assert_called_once()
        # The comment body should mention the PR number.
        comment_body = mock_post.call_args[0][1]
        assert "42" in comment_body

    def test_interview_skips_without_anthropic_key(self, tmp_path: Path) -> None:
        runner = CliRunner()

        mock_store = MagicMock()
        mock_store.exists.return_value = False

        with (
            patch("guardian.cli.MemoryStore", return_value=mock_store),
            patch("guardian.cli._load_config", return_value=GuardianConfig()),
        ):
            result = runner.invoke(
                cli,
                ["interview", "--repo-root", str(tmp_path)],
                env={"ANTHROPIC_API_KEY": ""},
            )

        assert result.exit_code == 0, result.output
        assert "skipping autonomous PR interview" in result.output

    def test_interview_fails_without_pr(self, tmp_path: Path) -> None:
        runner = CliRunner()

        payload = {"action": "created"}
        event_file = tmp_path / "event.json"
        event_file.write_text(json.dumps(payload), encoding="utf-8")

        mock_store = MagicMock()

        mock_ctx = MagicMock()
        mock_ctx.pr = None  # No PR in context.

        env = {
            "GITHUB_TOKEN": "test-token",
            "GITHUB_REPOSITORY": "test/repo",
            "GITHUB_EVENT_NAME": "pull_request",
            "ANTHROPIC_API_KEY": "test-key",
        }

        with (
            patch("guardian.cli.MemoryStore", return_value=mock_store),
            patch("guardian.cli.GitHubContext") as mock_ctx_cls,
            patch("guardian.cli._make_anthropic_client", return_value=MagicMock()),
            patch("guardian.cli._load_config", return_value=GuardianConfig()),
        ):
            mock_ctx_cls.from_env.return_value = mock_ctx

            result = runner.invoke(
                cli,
                ["interview", "--event-path", str(event_file), "--repo-root", str(tmp_path)],
                env=env,
            )

        assert result.exit_code != 0
