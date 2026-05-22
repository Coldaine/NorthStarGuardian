"""Orphan-branch memory I/O layer for NorthStarGuardian.

All Guardian state lives on the ``guardian-memory`` orphan branch, checked
out into a git worktree alongside the main working tree so CI can write to
it without touching ``main``.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Generator
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import Any


class MemoryError(Exception):
    """Base for memory-layer errors."""


class MemoryNotInitialized(MemoryError):
    """Raised when a read is attempted before the orphan branch exists."""


def _run(args: list[str], cwd: Path) -> str:
    """Run a git command, return stdout as a stripped string."""
    result = subprocess.run(
        args,
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


class MemoryStore:
    """Read/write interface for the ``guardian-memory`` orphan branch.

    Uses a git worktree so both the main branch and the memory branch are
    checked out simultaneously. The worktree is created lazily on the first
    read or write and reused for the lifetime of the process.

    Writes stage files immediately but do NOT commit automatically. Call
    :meth:`commit_and_push` explicitly, or use the :meth:`session` context
    manager to batch all writes into a single commit on exit.
    """

    def __init__(
        self,
        repo_root: Path,
        branch: str = "guardian-memory",
        worktree_path: Path | None = None,
    ) -> None:
        self.repo_root = repo_root
        self.branch = branch
        self.worktree_path: Path = worktree_path or repo_root / ".guardian-memory-worktree"
        self._worktree_ready = False

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def ensure_initialized(self) -> None:
        """Create the orphan branch and worktree if they do not yet exist.

        Detects the branch via ``git ls-remote``. If found, fetches it and
        attaches a worktree. If not found, creates an orphan branch with an
        initial commit (a single ``.gitkeep``) then pushes it to origin.
        """
        if self._worktree_ready:
            return

        branch_exists = self._remote_branch_exists()

        if branch_exists:
            self._attach_worktree()
        else:
            self._create_orphan_branch()

        self._worktree_ready = True

    def _remote_branch_exists(self) -> bool:
        """Return True if the branch exists on origin."""
        try:
            output = _run(
                ["git", "ls-remote", "--heads", "origin", self.branch],
                cwd=self.repo_root,
            )
            return bool(output)
        except subprocess.CalledProcessError:
            return False

    def _attach_worktree(self) -> None:
        """Fetch the remote branch and add a worktree for it."""
        # Fetch the branch so we have it locally.
        # Best-effort fetch; the local branch may already be current.
        with suppress(subprocess.CalledProcessError):
            _run(
                ["git", "fetch", "origin", self.branch],
                cwd=self.repo_root,
            )

        if self.worktree_path.exists():
            # Worktree already attached; nothing to do.
            return

        # Try adding the worktree using the remote-tracking ref.
        try:
            _run(
                [
                    "git", "worktree", "add",
                    str(self.worktree_path),
                    f"origin/{self.branch}",
                ],
                cwd=self.repo_root,
            )
        except subprocess.CalledProcessError:
            # Fall back: create local tracking branch first.
            # Best-effort branch creation; the remote may already have been pushed.
            with suppress(subprocess.CalledProcessError):
                _run(
                    ["git", "branch", self.branch, f"origin/{self.branch}"],
                    cwd=self.repo_root,
                )
            _run(
                [
                    "git", "worktree", "add",
                    str(self.worktree_path),
                    self.branch,
                ],
                cwd=self.repo_root,
            )

    def _create_orphan_branch(self) -> None:
        """Create a fresh orphan branch, commit .gitkeep, and push to origin."""
        # If the worktree path exists from a previous partial run, remove it.
        if self.worktree_path.exists():
            import shutil
            shutil.rmtree(str(self.worktree_path))

        # Add a worktree with a fresh orphan.  git worktree add --orphan was
        # introduced in git 2.38; we use the older approach (create orphan in a
        # scratch worktree via a temp env) for maximum compatibility.
        #
        # Strategy: create the worktree directory, init it as a bare working
        # tree, then create the orphan branch there.
        self.worktree_path.mkdir(parents=True, exist_ok=True)

        # Use git worktree add with --orphan (git >=2.38) and fall back to the
        # manual approach when it isn't available.
        try:
            _run(
                [
                    "git", "worktree", "add",
                    "--orphan", "-b", self.branch,
                    str(self.worktree_path),
                ],
                cwd=self.repo_root,
            )
        except subprocess.CalledProcessError:
            # Older git: create orphan manually inside the new dir.
            import shutil
            shutil.rmtree(str(self.worktree_path))
            self.worktree_path.mkdir(parents=True, exist_ok=True)
            _run(["git", "init"], cwd=self.worktree_path)
            _run(["git", "checkout", "--orphan", self.branch], cwd=self.worktree_path)
            _run(["git", "rm", "-rf", "."], cwd=self.worktree_path)

        # Create an initial commit so the branch has a valid HEAD.
        (self.worktree_path / ".gitkeep").touch()
        _run(["git", "add", ".gitkeep"], cwd=self.worktree_path)
        _run(
            ["git", "commit", "-m", "chore: initialise guardian-memory branch"],
            cwd=self.worktree_path,
        )

        # Push to origin so future runs can fetch it. Not fatal in offline / test envs.
        with suppress(subprocess.CalledProcessError):
            _run(
                ["git", "push", "origin", self.branch],
                cwd=self.worktree_path,
            )

    # ------------------------------------------------------------------
    # Guards
    # ------------------------------------------------------------------

    def _require_worktree(self) -> None:
        if not self._worktree_ready:
            raise MemoryNotInitialized(
                "Call ensure_initialized() before reading or writing memory."
            )

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def read(self, path: str) -> str:
        """Return the text content of *path* from the memory branch."""
        self._require_worktree()
        full = self.worktree_path / path
        if not full.exists():
            raise FileNotFoundError(f"guardian-memory:{path} does not exist")
        return full.read_text(encoding="utf-8")

    def read_json(self, path: str) -> Any:
        """Return the parsed JSON content of *path*."""
        return json.loads(self.read(path))

    def exists(self, path: str) -> bool:
        """Return True if *path* exists on the memory branch."""
        self._require_worktree()
        return (self.worktree_path / path).exists()

    # ------------------------------------------------------------------
    # Write (stages only; does not commit)
    # ------------------------------------------------------------------

    def write(self, path: str, content: str, message: str = "") -> None:
        """Write *content* to *path* and stage it.  Does not commit.

        *message* is ignored here; it is accepted so callers can document
        intent without breaking the API when they later call
        :meth:`commit_and_push`.
        """
        self._require_worktree()
        full = self.worktree_path / path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content, encoding="utf-8")
        _run(["git", "add", path], cwd=self.worktree_path)

    def write_json(self, path: str, obj: Any, message: str = "") -> None:
        """Serialise *obj* as pretty-printed JSON and write + stage it."""
        self.write(path, json.dumps(obj, indent=2, default=str), message)

    # ------------------------------------------------------------------
    # List
    # ------------------------------------------------------------------

    def list(self, prefix: str = "") -> list[str]:
        """Return relative paths of all tracked files, optionally filtered by *prefix*."""
        self._require_worktree()
        base = self.worktree_path / prefix if prefix else self.worktree_path
        if not base.exists():
            return []

        results: list[str] = []
        for p in sorted(base.rglob("*")):
            if p.is_file() and ".git" not in p.parts:
                rel = p.relative_to(self.worktree_path)
                results.append(str(rel).replace("\\", "/"))
        return results

    # ------------------------------------------------------------------
    # Commit & push
    # ------------------------------------------------------------------

    def commit_and_push(self, message: str, push: bool = True) -> None:
        """Commit all staged changes and optionally push to origin.

        If there is nothing staged, this is a no-op (prevents empty commits).
        """
        self._require_worktree()

        # Check whether there is anything to commit.
        status = _run(["git", "status", "--porcelain"], cwd=self.worktree_path)
        if not status:
            return  # nothing to commit

        # Stage any remaining unstaged changes (belt-and-suspenders).
        _run(["git", "add", "-A"], cwd=self.worktree_path)

        _run(
            ["git", "commit", "-m", message],
            cwd=self.worktree_path,
        )

        if push:
            # Not fatal — the commit succeeded locally.
            with suppress(subprocess.CalledProcessError):
                _run(
                    ["git", "push", "origin", self.branch],
                    cwd=self.worktree_path,
                )

    # ------------------------------------------------------------------
    # Session context manager
    # ------------------------------------------------------------------

    @contextmanager
    def session(self, message: str, push: bool = True) -> Generator[MemoryStore, None, None]:
        """Context manager that commits all writes on exit.

        Usage::

            with store.session("chore: update journal") as s:
                s.write("journal/2026-01-01-pr-1.md", body)
                s.write_json("drift-ledger.json", ledger)
        """
        yield self
        self.commit_and_push(message, push=push)
