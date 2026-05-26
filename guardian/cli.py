"""CLI entry point for NorthStarGuardian.

Each subcommand corresponds to one stage of the Guardian lifecycle described
in docs/SPEC.md §8–11.  The module is intentionally thin: all domain logic
lives in the imported modules; this file is only orchestration and I/O.
"""

from __future__ import annotations

import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import click
from anthropic import Anthropic

from guardian.github_io import GitHubContext, get_pr_diff, get_pr_meta, post_pr_comment
from guardian.memory import MemoryStore
from guardian.models import GuardianConfig
from guardian.north_star import (
    amend_north_star,
    initialize_north_star,
    read_north_star,
    write_north_star,
)

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
        raise click.ClickException(
            "ANTHROPIC_API_KEY environment variable is not set."
        )
    return Anthropic(api_key=api_key)


def _make_store(repo_root: Path | None = None) -> MemoryStore:
    """Create a MemoryStore rooted at *repo_root* (default: cwd)."""
    root = repo_root or Path(os.environ.get("GITHUB_WORKSPACE", ".")).resolve()
    return MemoryStore(root)


def parse_slash_command(body: str) -> tuple[str, list[str]] | None:
    """Parse a slash command from a comment body.

    Returns ``(command, args_list)`` when the body starts with ``/<cmd>``,
    or ``None`` if it doesn't match.

    Examples
    --------
    >>> parse_slash_command("/amend principle-3 new text")
    ('amend', ['principle-3', 'new text'])
    >>> parse_slash_command("not a command")
    None
    """
    body = body.strip()
    m = re.match(r"^/([a-zA-Z][\w-]*)(.*)$", body, re.DOTALL)
    if not m:
        return None

    cmd = m.group(1)
    rest = m.group(2).strip()

    # Split remainder into at most 2 tokens: the first word-token and the
    # rest (for cases like "/amend principle-3 "new text with spaces"").
    if rest:
        # Un-quote a quoted second argument if present.
        quoted = re.match(r'^(\S+)\s+"(.*)"$', rest, re.DOTALL)
        if quoted:
            args = [quoted.group(1), quoted.group(2)]
        else:
            parts = rest.split(None, 1)
            args = parts
    else:
        args = []

    return cmd, args


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

    # 3. Read North Star.
    north_star = read_north_star(store)

    # 4. Run LLM interview.
    report = analyze.run_interview(
        diff_analysis,
        north_star,
        client=client,
        model=config.anthropic_model_analysis,
    )

    # 5. Load existing sagas and assign the saga for this PR.
    # _load_saga_index and _saga_from_index_entry are module-internal helpers;
    # accessing them is acceptable here since cli.py is a first-party sibling.
    saga_index = chronicle._load_saga_index(store)
    all_sagas = [
        chronicle._saga_from_index_entry(entry)
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
    dashboard.render_dashboard(store, north_star)

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
# guardian command  (slash-command dispatcher)
# ---------------------------------------------------------------------------

@cli.command(name="command")
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
def command_dispatch(event_path: str | None, repo_root: str | None) -> None:
    """Handle issue_comment events containing slash commands."""
    root = Path(repo_root or ".").resolve()
    store = MemoryStore(root)

    ctx = GitHubContext.from_env(event_path=event_path)
    body = ctx.comment_body or ""

    parsed = parse_slash_command(body)
    if parsed is None:
        click.echo("Guardian: comment does not contain a slash command — skipping.")
        return

    cmd, args = parsed
    click.echo(f"Guardian: dispatching /{cmd} with args {args!r}")

    store.ensure_initialized()
    config = _load_config(store)

    handlers: dict[str, Any] = {
        "init-guardian": _handle_init_guardian,
        "re-anchor": _handle_re_anchor,
        "amend": _handle_amend,
        "chronicle": _handle_chronicle,
        "dashboard": _handle_dashboard,
        "status": _handle_status,
    }

    handler = handlers.get(cmd)
    if handler is None:
        reply = (
            f"Guardian: unknown command `/{cmd}`.\n\n"
            "Available commands: `/init-guardian`, `/re-anchor`, `/amend`, "
            "`/chronicle`, `/dashboard`, `/status`."
        )
        if ctx.pr:
            post_pr_comment(ctx, reply)
        else:
            click.echo(reply)
        return

    handler(ctx, store, config, args)


# ---------------------------------------------------------------------------
# Slash-command handlers
# ---------------------------------------------------------------------------

def _handle_init_guardian(
    ctx: GitHubContext,
    store: MemoryStore,
    config: GuardianConfig,
    args: list[str],
) -> None:
    """Handle /init-guardian — post instructions to run init-local."""
    reply = (
        "## Guardian Setup\n\n"
        "To initialize the Guardian North Star for this repository, run the "
        "following command locally:\n\n"
        "```\nguardian init-local\n```\n\n"
        "This will walk you through the guided setup flow interactively. "
        "Once complete, the North Star will be committed to the "
        "`guardian-memory` branch."
    )
    if ctx.pr:
        post_pr_comment(ctx, reply)
    else:
        click.echo(reply)


def _handle_re_anchor(
    ctx: GitHubContext,
    store: MemoryStore,
    config: GuardianConfig,
    args: list[str],
) -> None:
    """Handle /re-anchor — show current North Star summary and instructions."""
    try:
        north_star = read_north_star(store)
        principles_text = "\n".join(
            f"{p.rank}. {p.text}" for p in north_star.principles
        )
        reply = (
            f"## Guardian Re-Anchor\n\n"
            f"**Current identity:** {north_star.identity_statement}\n\n"
            f"**Principles:**\n{principles_text}\n\n"
            "To update these, run `guardian init-local` locally, or use "
            "`/amend <principle-id> \"new text\"` for targeted amendments."
        )
    except FileNotFoundError:
        reply = (
            "Guardian: no North Star found. Run `guardian init-local` first."
        )

    if ctx.pr:
        post_pr_comment(ctx, reply)
    else:
        click.echo(reply)


def _handle_amend(
    ctx: GitHubContext,
    store: MemoryStore,
    config: GuardianConfig,
    args: list[str],
) -> None:
    """Handle /amend <principle-id> "new text" — amend a specific principle."""
    if len(args) < 2:
        reply = (
            "Usage: `/amend <principle-id> \"new text\"`\n\n"
            "Example: `/amend p1 \"All data flows through the LLM layer\"`"
        )
        if ctx.pr:
            post_pr_comment(ctx, reply)
        else:
            click.echo(reply)
        return

    target_id = args[0]
    new_text = args[1]
    actor = ctx.event_payload.get("comment", {}).get("user", {}).get("login", "unknown")

    try:
        updated = amend_north_star(
            store,
            target="principle",
            target_id=target_id,
            after=new_text,
            rationale=f"Amended via /amend slash command by @{actor}",
            actor=actor,
        )
        with store.session(f"guardian: amend principle {target_id} via slash command"):
            pass

        reply = (
            f"## Guardian Amendment Applied\n\n"
            f"**Principle `{target_id}`** updated to:\n\n"
            f"> {new_text}\n\n"
            f"North Star version is now **v{updated.version}**."
        )
    except (ValueError, FileNotFoundError) as exc:
        reply = f"Guardian: amendment failed — {exc}"

    if ctx.pr:
        post_pr_comment(ctx, reply)
    else:
        click.echo(reply)


def _handle_chronicle(
    ctx: GitHubContext,
    store: MemoryStore,
    config: GuardianConfig,
    args: list[str],
) -> None:
    """Handle /chronicle — post recent chronicle entries."""
    from guardian import chronicle

    try:
        entries = chronicle.read_chronicle(store)
        if not entries:
            reply = "Guardian: no journal entries yet."
        else:
            # Post the 5 most recent entries.
            recent = entries[-5:]
            body_parts = ["## Guardian Chronicle (recent entries)\n"]
            for entry in reversed(recent):
                body_parts.append(entry.body_markdown)
                body_parts.append("\n---\n")
            reply = "\n".join(body_parts)
    except Exception as exc:
        reply = f"Guardian: error reading chronicle — {exc}"

    if ctx.pr:
        post_pr_comment(ctx, reply)
    else:
        click.echo(reply)


def _handle_dashboard(
    ctx: GitHubContext,
    store: MemoryStore,
    config: GuardianConfig,
    args: list[str],
) -> None:
    """Handle /dashboard — regenerate the dashboard and post a link."""
    from guardian import dashboard

    try:
        north_star = read_north_star(store)
        dashboard.render_dashboard(store, north_star)
        with store.session("guardian: regenerate dashboard via /dashboard command"):
            pass

        if config.pages_url:
            reply = (
                f"## Guardian Dashboard\n\n"
                f"Dashboard has been regenerated. "
                f"[View it here]({config.pages_url}/dashboard.html)."
            )
        else:
            reply = (
                "## Guardian Dashboard\n\n"
                "Dashboard has been regenerated on the `guardian-memory` branch. "
                "Browse to `dashboard.html` on that branch to view it, or configure "
                "`pages_url` in `meta/guardian-config.json` for a direct link."
            )
    except Exception as exc:
        reply = f"Guardian: error regenerating dashboard — {exc}"

    if ctx.pr:
        post_pr_comment(ctx, reply)
    else:
        click.echo(reply)


def _handle_status(
    ctx: GitHubContext,
    store: MemoryStore,
    config: GuardianConfig,
    args: list[str],
) -> None:
    """Handle /status — post a brief health summary."""
    from guardian import chronicle, governance

    lines: list[str] = ["## Guardian Status\n"]

    # Active debt timers.
    try:
        buckets = governance.check_debt_timers(store)
        active = buckets.get("active", [])
        approaching = buckets.get("approaching_expiry", [])
        expired = buckets.get("expired", [])
        if expired:
            lines.append(f"**Expired debt timers:** {len(expired)} (need resolution)")
        if approaching:
            lines.append(f"**Approaching expiry:** {len(approaching)}")
        if active:
            lines.append(f"**Active debt timers:** {len(active)}")
        if not active and not approaching and not expired:
            lines.append("**Debt timers:** none active")
    except Exception:
        lines.append("**Debt timers:** unavailable")

    lines.append("")

    # Last interview.
    try:
        entries = chronicle.read_chronicle(store)
        if entries:
            last = entries[-1]
            lines.append(
                f"**Last interview:** PR #{last.pr_number} "
                f"({last.timestamp.strftime('%Y-%m-%d')}) — `{last.verdict.value}`"
            )
        else:
            lines.append("**Last interview:** none recorded")
    except Exception:
        lines.append("**Last interview:** unavailable")

    if ctx.pr:
        post_pr_comment(ctx, "\n".join(lines))
    else:
        click.echo("\n".join(lines))


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

    # Post a tracking issue summarising escalations.
    token = os.environ.get("GITHUB_TOKEN")
    repo_name = os.environ.get("GITHUB_REPOSITORY")
    if token and repo_name:
        from github import Github

        gh = Github(token)
        repo = gh.get_repo(repo_name)

        lines = ["## Guardian Debt Escalation Report\n"]
        for debt in expired:
            lines.append(
                f"- PR #{debt.pr_number} — `{debt.principle_id}` "
                f"(expired {debt.expires_at.strftime('%Y-%m-%d')})"
            )
        body = "\n".join(lines)

        repo.create_issue(
            title=f"Guardian: {len(expired)} expired debt timer(s) — {datetime.now(tz=UTC).strftime('%Y-%m-%d')}",
            body=body,
            labels=["guardian", "tech-debt"],
        )
        click.echo("Guardian sweep-debt: tracking issue created.")


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
    """Interactive setup: walk through North Star initialization locally."""
    root = Path(repo_root).resolve()
    store = MemoryStore(root)

    click.echo("Guardian — North Star Setup")
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

    north_star = initialize_north_star(answers, actor="local-setup")

    click.echo("\nInitializing guardian-memory branch…")
    store.ensure_initialized()
    write_north_star(store, north_star, rationale="Initial North Star via init-local")

    with store.session("guardian: initialize North Star via init-local"):
        pass

    click.echo(
        f"\nNorth Star written for '{project_name}' with "
        f"{len(north_star.principles)} principles and "
        f"{len(north_star.anti_patterns)} anti-patterns."
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
        north_star = read_north_star(store)
    except FileNotFoundError as err:
        raise click.ClickException(
            "No North Star found on guardian-memory. Run `guardian init-local` first."
        ) from err

    html = dashboard.render_dashboard(store, north_star)

    out = Path(output)
    out.write_text(html, encoding="utf-8")
    click.echo(f"Dashboard written to: {out.resolve()}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Package entry point wired in pyproject.toml."""
    cli()
