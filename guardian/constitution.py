"""Constitutional tools for NorthStarGuardian.

Provides read/write/amend operations for the project Constitution stored on
the ``guardian-memory`` orphan branch, plus the amendment log.
"""

from __future__ import annotations

import json
import re
import textwrap
from datetime import UTC, datetime
from typing import Any

from jinja2 import Environment, PackageLoader

from guardian.memory import MemoryStore
from guardian.models import Amendment, AntiPattern, Constitution, Principle

# Paths on the guardian-memory branch.
_CONSTITUTION_PATH = "constitution.md"
_AMENDMENT_LOG_PATH = "meta/amendment-log.md"


# ---------------------------------------------------------------------------
# Markdown round-trip
# ---------------------------------------------------------------------------

_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)


def parse_constitution_markdown(text: str) -> Constitution:
    """Parse a Constitution from its Markdown+YAML-frontmatter representation."""
    m = _FRONTMATTER_RE.match(text)
    if not m:
        raise ValueError("constitution.md is missing YAML frontmatter")

    raw: dict[str, Any] = json.loads(m.group(1)) or {}

    principles = [
        Principle(
            id=p["id"],
            rank=p["rank"],
            text=p["text"],
            rationale=p.get("rationale"),
            tags=p.get("tags", []),
        )
        for p in raw.get("principles", [])
    ]

    anti_patterns = [
        AntiPattern(
            id=a["id"],
            description=a["description"],
            example=a.get("example"),
            detect=a.get("detect"),
        )
        for a in raw.get("anti_patterns", [])
    ]

    created_at = raw.get("created_at")
    if isinstance(created_at, str):
        created_at = datetime.fromisoformat(created_at)
    elif created_at is None:
        created_at = datetime.now(tz=UTC)

    amended_at = raw.get("amended_at")
    if isinstance(amended_at, str):
        amended_at = datetime.fromisoformat(amended_at)

    return Constitution(
        version=raw.get("version", 1),
        project_name=raw.get("project_name", ""),
        identity_statement=raw.get("identity_statement", ""),
        principles=principles,
        approved_architecture=raw.get("approved_architecture", ""),
        anti_patterns=anti_patterns,
        created_at=created_at,
        amended_at=amended_at,
    )


def render_constitution_markdown(c: Constitution) -> str:
    """Render a Constitution to the canonical Markdown+YAML-frontmatter format.

    The output is fully round-trippable via :func:`parse_constitution_markdown`.
    """
    frontmatter: dict[str, Any] = {
        "version": c.version,
        "project_name": c.project_name,
        "identity_statement": c.identity_statement,
        "approved_architecture": c.approved_architecture,
        "created_at": c.created_at.isoformat(),
        "principles": [
            {
                "id": p.id,
                "rank": p.rank,
                "text": p.text,
                **({"rationale": p.rationale} if p.rationale else {}),
                **({"tags": p.tags} if p.tags else {}),
            }
            for p in c.principles
        ],
        "anti_patterns": [
            {
                "id": a.id,
                "description": a.description,
                **({"example": a.example} if a.example else {}),
                **({"detect": a.detect} if a.detect else {}),
            }
            for a in c.anti_patterns
        ],
    }
    if c.amended_at:
        frontmatter["amended_at"] = c.amended_at.isoformat()

    yaml_block = json.dumps(frontmatter, indent=2, ensure_ascii=False, default=str)

    # Build the human-readable body after the frontmatter.
    body_lines = [
        f"# {c.project_name} — Constitution\n",
        "## Identity\n",
        c.identity_statement,
        "\n## Principles\n",
    ]
    for p in sorted(c.principles, key=lambda x: x.rank):
        body_lines.append(f"### {p.rank}. {p.text}\n")
        if p.rationale:
            body_lines.append(f"{p.rationale}\n")

    body_lines.append("\n## Approved Architecture\n")
    body_lines.append(c.approved_architecture)

    if c.anti_patterns:
        body_lines.append("\n\n## Anti-Patterns\n")
        for a in c.anti_patterns:
            body_lines.append(f"### {a.id}\n")
            body_lines.append(f"{a.description}\n")
            if a.example:
                body_lines.append(f"*Example:* {a.example}\n")
            if a.detect:
                body_lines.append(f"*Detect:* `{a.detect}`\n")

    body = "\n".join(body_lines)
    return f"---\n{yaml_block}\n---\n{body}\n"


# ---------------------------------------------------------------------------
# Core I/O
# ---------------------------------------------------------------------------

def read_constitution(store: MemoryStore) -> Constitution:
    """Read and parse the Constitution from the memory branch."""
    text = store.read(_CONSTITUTION_PATH)
    return parse_constitution_markdown(text)


def write_constitution(
    store: MemoryStore,
    c: Constitution,
    rationale: str = "initial",
) -> None:
    """Serialise and write *c* to the memory branch (stages; does not commit)."""
    store.write(_CONSTITUTION_PATH, render_constitution_markdown(c), message=rationale)


# ---------------------------------------------------------------------------
# Amendment
# ---------------------------------------------------------------------------

def amend_constitution(
    store: MemoryStore,
    target: str,
    target_id: str | None,
    after: str,
    rationale: str,
    actor: str,
) -> Constitution:
    """Apply an amendment to the Constitution and record it in the log.

    *target* must be one of ``"identity"``, ``"principle"``,
    ``"anti_pattern"``, or ``"architecture"``.

    Returns the updated Constitution (staged but not committed).
    """
    c = read_constitution(store)
    now = datetime.now(tz=UTC)
    before: str | None = None

    if target == "identity":
        before = c.identity_statement
        c = c.model_copy(update={"identity_statement": after, "amended_at": now})

    elif target == "architecture":
        before = c.approved_architecture
        c = c.model_copy(update={"approved_architecture": after, "amended_at": now})

    elif target == "principle":
        if target_id is None:
            raise ValueError("target_id is required when target='principle'")
        principles = list(c.principles)
        for i, p in enumerate(principles):
            if p.id == target_id:
                before = p.text
                principles[i] = p.model_copy(update={"text": after})
                break
        else:
            raise ValueError(f"Principle '{target_id}' not found in Constitution")
        c = c.model_copy(update={"principles": principles, "amended_at": now})

    elif target == "anti_pattern":
        if target_id is None:
            raise ValueError("target_id is required when target='anti_pattern'")
        patterns = list(c.anti_patterns)
        for i, a in enumerate(patterns):
            if a.id == target_id:
                before = a.description
                patterns[i] = a.model_copy(update={"description": after})
                break
        else:
            raise ValueError(f"Anti-pattern '{target_id}' not found in Constitution")
        c = c.model_copy(update={"anti_patterns": patterns, "amended_at": now})

    else:
        raise ValueError(
            f"Unknown amendment target '{target}'. "
            "Expected: identity, principle, anti_pattern, architecture"
        )

    c = c.model_copy(update={"version": c.version + 1})
    amendment = Amendment(
        timestamp=now,
        actor=actor,
        target=target,  # type: ignore[arg-type]
        target_id=target_id,
        before=before,
        after=after,
        rationale=rationale,
    )

    write_constitution(store, c, rationale=rationale)
    append_amendment(store, amendment)
    return c


def append_amendment(store: MemoryStore, amendment: Amendment) -> None:
    """Append *amendment* to the amendment log (stages; does not commit)."""
    existing = ""
    if store.exists(_AMENDMENT_LOG_PATH):
        existing = store.read(_AMENDMENT_LOG_PATH)

    entry = textwrap.dedent(f"""\
        ## {amendment.timestamp.strftime('%Y-%m-%d %H:%M UTC')} — {amendment.target}

        - **Actor:** {amendment.actor}
        - **Target:** {amendment.target}{f' / {amendment.target_id}' if amendment.target_id else ''}
        - **Rationale:** {amendment.rationale}

        **Before:**
        {amendment.before or '*(none)*'}

        **After:**
        {amendment.after}

        ---
    """)

    if not existing:
        header = "# Amendment Log\n\nAll constitutional changes, in chronological order.\n\n"
        content = header + entry
    else:
        content = existing + "\n" + entry

    store.write(_AMENDMENT_LOG_PATH, content)


# ---------------------------------------------------------------------------
# Initialize
# ---------------------------------------------------------------------------

def initialize_constitution(answers: dict[str, Any], actor: str) -> Constitution:
    """Turn a dict of setup-flow answers into a Constitution.

    The interactive prompts live in ``cli.py``; this function is pure
    data transformation.  Expected *answers* keys:

    - ``project_name`` (str)
    - ``identity_statement`` (str)
    - ``principles`` (list of str, 5–7 items)
    - ``approved_architecture`` (str)
    - ``anti_patterns`` (list of dict with ``description`` and optional
      ``example``, ``detect`` keys; or list of str for simple descriptions)

    Returns an un-persisted Constitution; call :func:`write_constitution`
    to save it.
    """
    now = datetime.now(tz=UTC)

    raw_principles: list[str | dict[str, Any]] = answers.get("principles", [])
    principles: list[Principle] = []
    for i, item in enumerate(raw_principles, start=1):
        if isinstance(item, str):
            principles.append(Principle(id=f"p{i}", rank=i, text=item))
        else:
            principles.append(
                Principle(
                    id=item.get("id", f"p{i}"),
                    rank=item.get("rank", i),
                    text=item["text"],
                    rationale=item.get("rationale"),
                    tags=item.get("tags", []),
                )
            )

    raw_patterns: list[str | dict[str, Any]] = answers.get("anti_patterns", [])
    anti_patterns: list[AntiPattern] = []
    for i, item in enumerate(raw_patterns, start=1):
        if isinstance(item, str):
            anti_patterns.append(AntiPattern(id=f"ap{i}", description=item))
        else:
            anti_patterns.append(
                AntiPattern(
                    id=item.get("id", f"ap{i}"),
                    description=item["description"],
                    example=item.get("example"),
                    detect=item.get("detect"),
                )
            )

    return Constitution(
        version=1,
        project_name=answers["project_name"],
        identity_statement=answers["identity_statement"],
        principles=principles,
        approved_architecture=answers.get("approved_architecture", ""),
        anti_patterns=anti_patterns,
        created_at=now,
    )


# ---------------------------------------------------------------------------
# Jinja2 template rendering (used by CLI)
# ---------------------------------------------------------------------------

def render_constitution_template(answers: dict[str, Any]) -> str:
    """Render the Jinja2 skeleton template with *answers* for preview/editing."""
    env = Environment(
        loader=PackageLoader("guardian", "templates"),
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template("constitution.md.j2")
    return template.render(**answers)
