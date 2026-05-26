from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from click.testing import CliRunner

from guardian.chronograph import (
    ActionClass,
    ChronographSafetyPolicy,
    ConfigDiff,
    RiskLevel,
    StewardshipAction,
    apply_plan,
    build_apply_plan,
    recommend_actions,
)
from guardian.cli import cli

NOW = datetime(2026, 5, 26, 12, 0, tzinfo=UTC)


def test_recommend_actions_turns_missing_include_diff_into_repair_action(tmp_path: Path) -> None:
    target = tmp_path / ".codex" / "AGENTS.md"
    diff = ConfigDiff(
        target_path=str(target),
        before="Always commit when feasible.\n",
        after="Always commit when feasible.\n@C:\\Users\\pmacl\\.codex\\RTK.md\n",
        summary="missing include @C:\\Users\\pmacl\\.codex\\RTK.md",
        source="memory-curation",
        confidence=0.96,
    )

    actions = recommend_actions([diff])

    assert len(actions) == 1
    action = actions[0]
    assert action.action_class == ActionClass.REPAIR
    assert action.metadata["operation"] == "add_missing_include"
    assert action.confidence == 0.96
    assert not action.destructive
    assert action.target_path == str(target)


def test_build_apply_plan_marks_high_confidence_additive_repair_auto_apply(tmp_path: Path) -> None:
    target = tmp_path / ".codex" / "AGENTS.md"
    target.parent.mkdir()
    target.write_text("Always commit when feasible.\n", encoding="utf-8")
    action = StewardshipAction(
        id="repair-missing-rtk",
        action_class=ActionClass.REPAIR,
        target_path=str(target),
        before="Always commit when feasible.\n",
        after="Always commit when feasible.\n@C:\\Users\\pmacl\\.codex\\RTK.md\n",
        reason="The diff showed AGENTS.md missing the durable RTK include.",
        confidence=0.96,
        metadata={"operation": "add_missing_include"},
    )
    policy = ChronographSafetyPolicy.for_repo(tmp_path)

    plan = build_apply_plan([action], policy=policy, now=NOW)

    assert len(plan) == 1
    item = plan[0]
    assert item.action_id == "repair-missing-rtk"
    assert item.risk_level == RiskLevel.LOW
    assert item.auto_apply
    assert str(tmp_path / ".github" / "guardian" / "chronograph" / "backups") in item.backup_path
    assert "@@ " in item.diff
    assert "Copy-Item" in item.rollback_command


def test_apply_plan_recomputes_auto_apply_from_source_action(tmp_path: Path) -> None:
    target = tmp_path / ".claude" / "agents" / "old.md"
    target.parent.mkdir(parents=True)
    before = "stale agent\n"
    target.write_text(before, encoding="utf-8")
    action = StewardshipAction(
        id="retire-old-agent",
        action_class=ActionClass.RETIRE,
        target_path=str(target),
        before=before,
        after="",
        reason="Timeline shows this agent is no longer referenced.",
        confidence=0.99,
        destructive=True,
        approved=False,
    )
    policy = ChronographSafetyPolicy.for_repo(tmp_path)
    plan = build_apply_plan([action], policy=policy, now=NOW)
    tampered = plan[0].model_copy(update={"auto_apply": True})

    results = apply_plan([tampered], policy=policy, actions=[action], now=NOW)

    assert not results[0].applied
    assert results[0].skipped_reason == "action requires explicit approval"
    assert target.read_text(encoding="utf-8") == before


def test_apply_plan_skips_when_live_target_changed_since_planning(tmp_path: Path) -> None:
    target = tmp_path / ".codex" / "AGENTS.md"
    target.parent.mkdir()
    before = "Always commit when feasible.\n"
    target.write_text(before, encoding="utf-8")
    action = StewardshipAction(
        id="repair-missing-rtk",
        action_class=ActionClass.REPAIR,
        target_path=str(target),
        before=before,
        after=before + "@C:\\Users\\pmacl\\.codex\\RTK.md\n",
        reason="The diff showed AGENTS.md missing the durable RTK include.",
        confidence=0.96,
        metadata={"operation": "add_missing_include", "include": "@C:\\Users\\pmacl\\.codex\\RTK.md"},
    )
    policy = ChronographSafetyPolicy.for_repo(tmp_path)
    plan = build_apply_plan([action], policy=policy, now=NOW)
    target.write_text("User changed this file after the plan.\n", encoding="utf-8")

    results = apply_plan(plan, policy=policy, actions=[action], now=NOW)

    assert not results[0].applied
    assert results[0].skipped_reason == "target changed since plan"
    assert target.read_text(encoding="utf-8") == "User changed this file after the plan.\n"


def test_approved_destructive_action_is_not_marked_auto_apply(tmp_path: Path) -> None:
    target = tmp_path / ".claude" / "agents" / "old.md"
    target.parent.mkdir(parents=True)
    target.write_text("stale agent\n", encoding="utf-8")
    action = StewardshipAction(
        id="retire-old-agent",
        action_class=ActionClass.RETIRE,
        target_path=str(target),
        before="stale agent\n",
        after="",
        reason="Timeline shows this agent is no longer referenced.",
        confidence=0.99,
        destructive=True,
        approved=True,
    )

    plan = build_apply_plan(
        [action],
        policy=ChronographSafetyPolicy.for_repo(tmp_path),
        now=NOW,
    )

    assert plan[0].approved
    assert not plan[0].auto_apply


def test_arbitrary_missing_include_is_not_auto_applied(tmp_path: Path) -> None:
    target = tmp_path / ".codex" / "AGENTS.md"
    target.parent.mkdir()
    before = "Always commit when feasible.\n"
    target.write_text(before, encoding="utf-8")
    diff = ConfigDiff(
        target_path=str(target),
        before=before,
        after=before + "@C:\\Users\\pmacl\\.codex\\UNREVIEWED.md\n",
        summary="missing include @C:\\Users\\pmacl\\.codex\\UNREVIEWED.md",
        source="memory-curation",
        confidence=0.96,
    )
    action = recommend_actions([diff])[0]

    plan = build_apply_plan(
        [action],
        policy=ChronographSafetyPolicy.for_repo(tmp_path),
        now=NOW,
    )

    assert action.action_class == ActionClass.REPAIR
    assert not plan[0].auto_apply


def test_new_file_apply_plan_uses_remove_item_rollback(tmp_path: Path) -> None:
    target = tmp_path / ".codex" / "AGENTS.md"
    action = StewardshipAction(
        id="create-agents",
        action_class=ActionClass.REPAIR,
        target_path=str(target),
        before="",
        after="@C:\\Users\\pmacl\\.codex\\RTK.md\n",
        reason="The diff showed AGENTS.md missing the durable RTK include.",
        confidence=0.96,
        metadata={"operation": "add_missing_include", "include": "@C:\\Users\\pmacl\\.codex\\RTK.md"},
    )

    plan = build_apply_plan(
        [action],
        policy=ChronographSafetyPolicy.for_repo(tmp_path),
        now=NOW,
    )

    assert plan[0].target_existed is False
    assert "Remove-Item" in plan[0].rollback_command


def test_sqlite_state_files_are_forbidden_by_suffix(tmp_path: Path) -> None:
    target = tmp_path / ".codex" / "memory" / "state.sqlite3"
    action = StewardshipAction(
        id="bad-sqlite-write",
        action_class=ActionClass.REPAIR,
        target_path=str(target),
        before="",
        after="sqlite bytes",
        reason="Should never be allowed.",
        confidence=1.0,
    )

    with pytest.raises(ValueError, match="forbidden"):
        build_apply_plan([action], policy=ChronographSafetyPolicy.for_repo(tmp_path), now=NOW)


def test_build_apply_plan_allows_home_level_tool_roots(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    target = home / ".codex" / "AGENTS.md"
    target.parent.mkdir(parents=True)
    target.write_text("Always commit when feasible.\n", encoding="utf-8")
    monkeypatch.setattr("guardian.chronograph.Path.home", staticmethod(lambda: home))
    action = StewardshipAction(
        id="repair-home-root",
        action_class=ActionClass.REPAIR,
        target_path=str(target),
        before="Always commit when feasible.\n",
        after="Always commit when feasible.\n@C:\\Users\\pmacl\\.codex\\RTK.md\n",
        reason="The diff showed a home-level Codex include was missing.",
        confidence=0.96,
        metadata={"operation": "add_missing_include"},
    )

    plan = build_apply_plan(
        [action],
        policy=ChronographSafetyPolicy.for_repo(tmp_path / "repo"),
        now=NOW,
    )

    assert plan[0].auto_apply
    assert plan[0].target_path == str(target.resolve())


def test_apply_plan_creates_backup_and_audit_for_live_write(tmp_path: Path) -> None:
    target = tmp_path / ".codex" / "AGENTS.md"
    target.parent.mkdir()
    before = "Always commit when feasible.\n"
    after = before + "@C:\\Users\\pmacl\\.codex\\RTK.md\n"
    target.write_text(before, encoding="utf-8")
    action = StewardshipAction(
        id="repair-missing-rtk",
        action_class=ActionClass.REPAIR,
        target_path=str(target),
        before=before,
        after=after,
        reason="The diff showed AGENTS.md missing the durable RTK include.",
        confidence=0.96,
        metadata={"operation": "add_missing_include"},
    )
    policy = ChronographSafetyPolicy.for_repo(tmp_path)
    plan = build_apply_plan([action], policy=policy, now=NOW)

    results = apply_plan(plan, policy=policy, actions=[action], now=NOW)

    assert target.read_text(encoding="utf-8") == after
    assert len(results) == 1
    result = results[0]
    assert result.applied
    assert result.backup_path is not None
    assert Path(result.backup_path).read_text(encoding="utf-8") == before
    audit_path = tmp_path / ".github" / "guardian" / "chronograph" / "audit.jsonl"
    audit = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]
    assert audit[-1]["action_id"] == "repair-missing-rtk"
    assert audit[-1]["old_hash"] == result.old_hash
    assert audit[-1]["new_hash"] == result.new_hash
    assert audit[-1]["backup_path"] == result.backup_path


def test_forbidden_paths_are_rejected_before_planning(tmp_path: Path) -> None:
    token_file = tmp_path / ".codex" / "auth.json"
    token_file.parent.mkdir()
    token_file.write_text('{"token":"secret"}', encoding="utf-8")
    action = StewardshipAction(
        id="bad-token-write",
        action_class=ActionClass.REPAIR,
        target_path=str(token_file),
        before='{"token":"secret"}',
        after='{"token":"other"}',
        reason="Should never be allowed.",
        confidence=1.0,
    )

    with pytest.raises(ValueError, match="forbidden"):
        build_apply_plan([action], policy=ChronographSafetyPolicy.for_repo(tmp_path), now=NOW)


def test_destructive_retire_action_is_not_auto_applied(tmp_path: Path) -> None:
    target = tmp_path / ".claude" / "agents" / "old.md"
    target.parent.mkdir(parents=True)
    target.write_text("stale agent\n", encoding="utf-8")
    action = StewardshipAction(
        id="retire-old-agent",
        action_class=ActionClass.RETIRE,
        target_path=str(target),
        before="stale agent\n",
        after="",
        reason="Timeline shows this agent is no longer referenced.",
        confidence=0.99,
        destructive=True,
        approved=False,
    )

    plan = build_apply_plan(
        [action],
        policy=ChronographSafetyPolicy.for_repo(tmp_path),
        now=NOW,
    )
    results = apply_plan(
        plan,
        policy=ChronographSafetyPolicy.for_repo(tmp_path),
        actions=[action],
        now=NOW,
    )

    assert plan[0].risk_level == RiskLevel.HIGH
    assert not plan[0].auto_apply
    assert not results[0].applied
    assert target.read_text(encoding="utf-8") == "stale agent\n"


def test_chronograph_cli_writes_recommendations_plan_and_audit(tmp_path: Path) -> None:
    runner = CliRunner()
    target = tmp_path / ".codex" / "AGENTS.md"
    target.parent.mkdir()
    target.write_text("Always commit when feasible.\n", encoding="utf-8")
    chronograph_dir = tmp_path / ".github" / "guardian" / "chronograph"
    chronograph_dir.mkdir(parents=True)
    diff = ConfigDiff(
        target_path=str(target),
        before=target.read_text(encoding="utf-8"),
        after="Always commit when feasible.\n@C:\\Users\\pmacl\\.codex\\RTK.md\n",
        summary="missing include @C:\\Users\\pmacl\\.codex\\RTK.md",
        source="memory-curation",
        confidence=0.96,
    )
    (chronograph_dir / "diffs.json").write_text(
        json.dumps([diff.model_dump(mode="json")], indent=2),
        encoding="utf-8",
    )

    recommend = runner.invoke(
        cli,
        ["chronograph-recommend-actions", "--repo-root", str(tmp_path)],
    )
    plan = runner.invoke(
        cli,
        ["chronograph-plan-apply", "--repo-root", str(tmp_path)],
    )
    applied = runner.invoke(
        cli,
        ["chronograph-apply", "--repo-root", str(tmp_path)],
    )

    assert recommend.exit_code == 0, recommend.output
    assert plan.exit_code == 0, plan.output
    assert applied.exit_code == 0, applied.output
    assert (chronograph_dir / "recommendations.json").exists()
    assert (chronograph_dir / "apply-plan.json").exists()
    assert (chronograph_dir / "audit.jsonl").exists()
    assert "@C:\\Users\\pmacl\\.codex\\RTK.md" in target.read_text(encoding="utf-8")
