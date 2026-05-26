"""Tests for Linear integration helpers."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import pytest

from guardian.linear import LinearAPIError, LinearClient, normalize_markdown


class StubLinearClient(LinearClient):
    def __init__(self, responses: list[dict[str, Any]]) -> None:
        super().__init__(api_key="test-key")
        self.responses = responses
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def graphql(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((query, variables))
        return self.responses.pop(0)


def test_normalize_markdown_normalizes_line_endings_and_trailing_newline() -> None:
    assert normalize_markdown("hello\r\nworld  \r\n") == "hello\nworld\n"


def test_fetch_document_returns_snapshot_with_hash_and_metadata() -> None:
    client = StubLinearClient(
        [
            {
                "document": {
                    "id": "doc-1",
                    "title": "Repo North Star",
                    "content": "# Policy\r\n",
                    "documentContentId": "content-1",
                    "updatedAt": "2026-05-26T12:00:00.000Z",
                    "url": "https://linear.app/acme/document/doc-1",
                    "updatedBy": {"id": "user-1", "name": "Ada"},
                }
            }
        ]
    )

    snapshot = client.fetch_document("doc-1", fetched_at=datetime(2026, 5, 26, 12, 1))

    assert snapshot.provider == "linear"
    assert snapshot.document_id == "doc-1"
    assert snapshot.document_content_id == "content-1"
    assert snapshot.updated_by == "Ada"
    assert snapshot.content == "# Policy\n"
    assert len(snapshot.sha256) == 64
    assert client.calls[0][1] == {"id": "doc-1"}


def test_fetch_document_raises_for_missing_document() -> None:
    client = StubLinearClient([{"document": None}])

    with pytest.raises(LinearAPIError, match="not found"):
        client.fetch_document("missing")


def test_graphql_raises_for_errors() -> None:
    client = LinearClient(api_key="test-key")

    with pytest.raises(LinearAPIError, match="boom"):
        client._parse_response(json.dumps({"errors": [{"message": "boom"}]}))


def test_create_issue_returns_issue_metadata() -> None:
    client = StubLinearClient(
        [
            {
                "issueCreate": {
                    "success": True,
                    "issue": {
                        "id": "issue-1",
                        "identifier": "GUAR-123",
                        "title": "Drift detected",
                        "url": "https://linear.app/acme/issue/GUAR-123",
                    },
                }
            }
        ]
    )

    issue = client.create_issue(
        team_id="team-1",
        title="Drift detected",
        description="Review summary",
        project_id="project-1",
    )

    assert issue.identifier == "GUAR-123"
    assert issue.url.endswith("GUAR-123")
    assert client.calls[0][1]["input"]["teamId"] == "team-1"
    assert client.calls[0][1]["input"]["projectId"] == "project-1"
