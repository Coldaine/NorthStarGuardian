"""Tests for Guardian runtime configuration models."""

from __future__ import annotations

from guardian.models import GuardianConfig


def test_guardian_config_defaults_to_repo_north_star_source() -> None:
    config = GuardianConfig()

    assert config.north_star.source == "repo"
    assert config.north_star.repo_path == "docs/northstar.md"
    assert config.north_star.active_copy_path == ".github/guardian/northstar.md"


def test_guardian_config_has_linear_section() -> None:
    config = GuardianConfig(
        north_star={"source": "linear"},
        linear={"document_id": "doc-1", "team_id": "team-1"},
    )

    assert config.north_star.source == "linear"
    assert config.linear.document_id == "doc-1"
    assert config.linear.team_id == "team-1"


def test_guardian_config_no_longer_exposes_legacy_storage_branch_field() -> None:
    config = GuardianConfig()

    assert not hasattr(config, "memory" + "_branch")
