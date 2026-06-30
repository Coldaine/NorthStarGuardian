"""Tests for github_io.py"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from guardian.github_io import GitHubContext, get_pr_diff, get_pr_meta, post_pr_comment


@pytest.fixture
def mock_github():
    with patch("guardian.github_io.Github") as mock:
        yield mock


def test_github_context_from_env_pull_request(tmp_path, mock_github):
    event_path = tmp_path / "event.json"
    event_payload = {
        "pull_request": {"number": 123},
        "repository": {"full_name": "owner/repo"},
    }
    event_path.write_text(json.dumps(event_payload))

    mock_repo = MagicMock()
    mock_github.return_value.get_repo.return_value = mock_repo

    env = {
        "GITHUB_TOKEN": "secret",
        "GITHUB_REPOSITORY": "owner/repo",
        "GITHUB_EVENT_NAME": "pull_request",
        "GITHUB_EVENT_PATH": str(event_path),
    }

    with patch.dict("os.environ", env):
        ctx = GitHubContext.from_env()

    assert ctx.event_name == "pull_request"
    assert ctx.pr is not None
    mock_repo.get_pull.assert_called_once_with(123)


def test_github_context_from_env_issue_comment(tmp_path, mock_github):
    event_path = tmp_path / "event.json"
    event_payload = {
        "issue": {"number": 123},
        "comment": {"body": "/amend p1"},
    }
    event_path.write_text(json.dumps(event_payload))

    mock_repo = MagicMock()
    mock_github.return_value.get_repo.return_value = mock_repo

    env = {
        "GITHUB_TOKEN": "secret",
        "GITHUB_REPOSITORY": "owner/repo",
        "GITHUB_EVENT_NAME": "issue_comment",
        "GITHUB_EVENT_PATH": str(event_path),
    }

    with patch.dict("os.environ", env):
        ctx = GitHubContext.from_env()

    assert ctx.event_name == "issue_comment"
    assert ctx.comment_body == "/amend p1"
    mock_repo.get_pull.assert_called_once_with(123)


def test_post_pr_comment(mock_github):
    mock_pr = MagicMock()
    ctx = GitHubContext(repo=MagicMock(), event_name="test", event_payload={}, pr=mock_pr)

    post_pr_comment(ctx, "Hello world")

    mock_pr.create_issue_comment.assert_called_once_with("Hello world")


def test_get_pr_diff(mock_github):
    mock_file = MagicMock()
    mock_file.filename = "file.txt"
    mock_file.patch = "@@ -1 +1 @@\n-old\n+new"

    mock_pr = MagicMock()
    mock_pr.get_files.return_value = [mock_file]

    ctx = GitHubContext(repo=MagicMock(), event_name="test", event_payload={}, pr=mock_pr)

    diff = get_pr_diff(ctx)

    assert "diff --git a/file.txt b/file.txt" in diff
    assert "+new" in diff


def test_get_pr_meta(mock_github):
    mock_pr = MagicMock()
    mock_pr.number = 123
    mock_pr.title = "Fix"
    mock_pr.body = "Desc"
    mock_pr.user.login = "alice"
    mock_pr.base.sha = "base"
    mock_pr.head.sha = "head"
    mock_pr.base.ref = "main"
    mock_pr.head.ref = "feature"
    mock_pr.html_url = "http://github.com/PR/123"
    
    ctx = GitHubContext(repo=MagicMock(), event_name="test", event_payload={}, pr=mock_pr)

    meta = get_pr_meta(ctx)

    assert meta["number"] == 123
    assert meta["author"] == "alice"
    assert meta["base_sha"] == "base"
