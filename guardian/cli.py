"""CLI entry point for NorthStarGuardian.

Each subcommand corresponds to one agent-side stage of the Guardian lifecycle
described in docs/SPEC.md.  The module is intentionally thin: all domain logic
lives in the imported modules; this file is only orchestration and I/O.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import click
from anthropic import Anthropic

from guardian.constitution import initialize_constitution, read_constitution, write_constitution
from guardian.github_io import GitHubContext, get_pr_diff, get_pr_meta, post_pr_comment
from guardian.memory import MemoryStore
from guardian.models import GuardianConfig

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CONFIG_PATH = "meta/guardian-config.json"


def _load_config(store: MemoryStore) -> GuardianConfig:
    """Read GuardianConfig from the memory branch, defaulting if absent."""
    if store.exists(_CONFIG_PATH):
        try:
            raw = store.read_json(_CONFIG_PATH)
            return GuardianConfig(**raw)
        except Exception:
            pass
    return GuardianConfig()


def _make_anthropic_client() -> Anthropic:
    """Construct an Anthropic client from the environment."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise click.ClickException("ANTHROPIC_API_KEY environment variable is not set.")
    return Anthropic(api_key=api_key)


def _anthropic_key_configured() -> bool:
    """Return whether the autonomous interview has model credentials available."""
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def _make_store(repo_root: Path | None = None) -> MemoryStore:
    """Create a MemoryStore rooted at *repo_root* (default: cwd)."""
    root = repo_root or Path(os.environ.get("GITHUB_WORKSPACE", ".")).resolve()
    return MemoryStore(root)


def _format_report_comment(report: Any, config: GuardianConfig) -> str:
    """Render an InterviewReport as a Markdown PR comment."""
    from guardian.models import Verdict

    verdict_emoji = {
        Verdict.ALIGNED: "✅",
        Verdict.AMBIGUOUS: "⚠️",
        Verdict.DRIFT: "🔴",
    }
    emoji = verdict_emoji.get(report.overall_verdict, "🔵")

    lines: list[str] = [
        f"## {emoji} Guardian Interview — PR #{report.pr_number}",
        "",
        f"**{report.alignment_summary}**",
        "",
    ]

    # Principle evaluations — only the relevant ones.
    relevant = [pe for pe in report.principle_evaluations if pe.relevant]
    if relevant:
        lines.append("### Principle Check")
        for pe in relevant:
            v_emoji = verdict_emoji.get(pe.verdict, "🔵") if pe.verdict else "🔵"
            lines.append(f"- {v_emoji} **{pe.principle_id}**: {pe.reasoning or ''}")
        lines.append("")

    # Anti-pattern matches.
    if report.anti_pattern_matches:
        lines.append("### Anti-Pattern Matches")
        for m in report.anti_pattern_matches:
            lines.append(f"- `{m.location}` — {m.explanation}")
        lines.append("")

    # Saga.
    if report.saga_id:
        lines.append(f"**Saga:** `{report.saga_id}`")
        lines.append("")

    # Suggestions.
    if report.suggestions:
        lines.append("### Suggestions")
        for s in report.suggestions:
            lines.append(f"- {s}")
        lines.append("")

    # Chronicle paragraph.
    lines.append("### Chronicle Entry")
    lines.append(report.chronicle_paragraph)
    lines.append("")

    # Footer.
    if config.pages_url:
        lines.append(f"[View Dashboard]({config.pages_url}/dashboard.html)")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI root
# ---------------------------------------------------------------------------

@click.group()
def cli() -> None:
    """NorthStarGuardian — advisory PR governance agent."""


# ---------------------------------------------------------------------------
# guardian interview
# ---------------------------------------------------------------------------

@cli.command()
@click.option(
    "--event-path",
    default=None,
    envvar="GITHUB_EVENT_PATH",
    help="Path to the GitHub event JSON payload.",
)
@click.option(
    "--repo-root",
    default=None,
    envvar="GITHUB_WORKSPACE",
    help="Repository root directory.",
)
def interview(event_path: str | None, repo_root: str | None) -> None:
    """Run the full PR interview cycle (triggered by pull_request events)."""
    # Lazy imports of domain modules so tests can mock them before importing cli.
    from guardian import analyze, chronicle, dashboard

    root = Path(repo_root or ".").resolve()
    store = MemoryStore(root)
    store.ensure_initialized()

    config = _load_config(store)
    if not _anthropic_key_configured():
        click.echo(
            "Guardian: ANTHROPIC_API_KEY is not configured; "
            "skipping autonomous PR interview."
        )
        return
    client = _make_anthropic_client()

    # Build GitHub context.
    ctx = GitHubContext.from_env(event_path=event_path)
    if ctx.pr is None:
        raise click.ClickException("No pull request found in event payload.")

    click.echo(f"Guardian: interviewing PR #{ctx.pr.number}")

    # 1. Read diff and metadata.
    diff = get_pr_diff(ctx)
    meta = get_pr_meta(ctx)

    # 2. Analyze diff (pre-LLM structural extraction).
    diff_analysis = analyze.analyze_diff(diff, meta)

    # 3. Read constitution.
    constitution = read_constitution(store)

    # 4. Run LLM interview.
    report = analyze.run_interview(
        diff_analysis,
        constitution,
        client=client,
        model=config.anthropic_model_analysis,
    )

    # 5. Load existing sagas and assign the saga for this PR.
    saga_index = chronicle.load_saga_index(store)
    all_sagas = [
        chronicle.saga_from_index_entry(entry)
        for entry in saga_index.get("sagas", [])
    ]
    saga = chronicle.assign_saga(
        store,
        report.intent,
        all_sagas,
        client=client,
        model=config.anthropic_model_analysis,
    )
    chronicle.update_saga(store, saga, report.pr_number)
    report = report.model_copy(update={"saga_id": saga.id})

    # 6. Write journal entry.
    chronicle.write_journal_entry(store, report, saga)

    # 7. Render dashboard.
    dashboard.render_dashboard(store, constitution)

    # 8. Commit everything to guardian-memory.
    pr_num = ctx.pr.number
    with store.session(
        f"guardian: interview PR #{pr_num} — {report.overall_verdict.value}"
    ):
        pass  # session commits whatever was staged by the above calls

    # 9. Post report as a PR comment.
    comment_body = _format_report_comment(report, config)
    post_pr_comment(ctx, comment_body)

    click.echo(f"Guardian: interview complete — verdict: {report.overall_verdict.value}")


# ---------------------------------------------------------------------------
# guardian sweep-debt
# ---------------------------------------------------------------------------

@cli.command()
@click.option(
    "--repo-root",
    default=None,
    envvar="GITHUB_WORKSPACE",
    help="Repository root directory.",
)
def sweep_debt(repo_root: str | None) -> None:
    """Scheduled job: check debt timers and escalate expired ones."""
    from guardian import governance

    root = Path(repo_root or ".").resolve()
    store = MemoryStore(root)
    store.ensure_initialized()

    buckets = governance.check_debt_timers(store)
    active = buckets.get("active", [])
    approaching = buckets.get("approaching_expiry", [])
    expired = buckets.get("expired", [])
    click.echo(
        f"Guardian sweep-debt: {len(active)} active, "
        f"{len(approaching)} approaching, {len(expired)} expired timers"
    )

    if not expired and not approaching:
        click.echo("Guardian sweep-debt: nothing to escalate.")
        return

    from guardian.models import DebtLevel

    config = _load_config(store)

    for debt in approaching:
        governance.escalate_debt(
            store, debt.id, new_level=DebtLevel.REMINDER_75, config=config
        )
        click.echo(f"  Reminded (75%) debt {debt.id} (PR #{debt.pr_number}, {debt.principle_id})")

    for debt in expired:
        governance.escalate_debt(
            store, debt.id, new_level=DebtLevel.REMINDER_EXPIRED, config=config
        )
        click.echo(f"  Escalated debt {debt.id} (PR #{debt.pr_number}, {debt.principle_id})")

    with store.session("guardian: sweep-debt escalation run"):
        pass
    click.echo("Guardian sweep-debt: memory updated; no issue or command surface created.")


# ---------------------------------------------------------------------------
# guardian init-local
# ---------------------------------------------------------------------------

@cli.command()
@click.option(
    "--repo-root",
    default=".",
    show_default=True,
    help="Repository root directory.",
)
def init_local(repo_root: str) -> None:
    """Interactive setup: walk through constitution initialization locally."""
    root = Path(repo_root).resolve()
    store = MemoryStore(root)

    click.echo("Guardian — Constitution Setup")
    click.echo("=" * 40)

    # Project identity.
    project_name = click.prompt("Project name")
    click.echo(
        "\nProject identity statement: one paragraph describing what this project IS "
        "and what it is NOT. (e.g. 'This is an LLM-powered analysis pipeline. "
        "It is not a collection of standalone scripts.')"
    )
    identity_statement = click.prompt("Identity statement")

    # Principles (5-7).
    click.echo(
        "\nPrinciples: enter 5–7 rank-ordered tenets that define the project's soul. "
        "Press Enter with an empty line to stop (minimum 5)."
    )
    raw_principles: list[str] = []
    while len(raw_principles) < 7:
        n = len(raw_principles) + 1
        value = click.prompt(f"Principle {n}", default="", show_default=False)
        if not value:
            if len(raw_principles) >= 5:
                break
            click.echo(f"  Please enter at least {5 - len(raw_principles)} more principle(s).")
        else:
            raw_principles.append(value)

    # Approved architecture paragraph.
    click.echo(
        "\nApproved architecture: one paragraph describing the canonical packages, "
        "patterns, and paradigms. (e.g. 'We use Gin for HTTP, GORM for persistence.')"
    )
    approved_architecture = click.prompt("Approved architecture")

    # Anti-patterns (optional).
    click.echo(
        "\nAnti-patterns: explicit examples of what drift looks like. "
        "Press Enter with an empty line to skip."
    )
    raw_anti_patterns: list[str] = []
    while True:
        n = len(raw_anti_patterns) + 1
        value = click.prompt(f"Anti-pattern {n} (or Enter to finish)", default="", show_default=False)
        if not value:
            break
        raw_anti_patterns.append(value)

    answers: dict[str, Any] = {
        "project_name": project_name,
        "identity_statement": identity_statement,
        "principles": raw_principles,
        "approved_architecture": approved_architecture,
        "anti_patterns": raw_anti_patterns,
    }

    constitution = initialize_constitution(answers, actor="local-setup")

    click.echo("\nInitializing guardian-memory branch…")
    store.ensure_initialized()
    write_constitution(store, constitution, rationale="Initial constitution via init-local")

    with store.session("guardian: initialize constitution via init-local"):
        pass

    click.echo(
        f"\nConstitution written for '{project_name}' with "
        f"{len(constitution.principles)} principles and "
        f"{len(constitution.anti_patterns)} anti-patterns."
    )
    click.echo("Guardian is ready.")


# ---------------------------------------------------------------------------
# guardian preview-dashboard
# ---------------------------------------------------------------------------

@cli.command()
@click.option(
    "--output",
    default="dashboard-preview.html",
    show_default=True,
    help="Output HTML file path.",
)
@click.option(
    "--repo-root",
    default=".",
    show_default=True,
    help="Repository root directory.",
)
def preview_dashboard(output: str, repo_root: str) -> None:
    """Local dev: render the dashboard to a local HTML file."""
    from guardian import dashboard

    root = Path(repo_root).resolve()
    store = MemoryStore(root)
    store.ensure_initialized()

    try:
        constitution = read_constitution(store)
    except FileNotFoundError as err:
        raise click.ClickException(
            "No Constitution found on guardian-memory. Run `guardian init-local` first."
        ) from err

    html = dashboard.render_dashboard(store, constitution)

    out = Path(output)
    out.write_text(html, encoding="utf-8")
    click.echo(f"Dashboard written to: {out.resolve()}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Package entry point wired in pyproject.toml."""
    cli()
