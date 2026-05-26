"""Tests for guardian.memory — orphan-branch I/O layer.

All tests create a fresh git repository inside tmp_path so they run fully
offline. No network calls are made.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from guardian.memory import MemoryNotInitialized, MemoryStore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _git(args: list[str], cwd: Path) -> str:
    """Run a git command in *cwd*, return stdout."""
    result = subprocess.run(
        ["git"] + args,
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _make_repo(path: Path) -> Path:
    """Initialise a bare-minimum git repo at *path* with one commit on main."""
    path.mkdir(parents=True, exist_ok=True)
    _git(["init", "-b", "main"], cwd=path)
    _git(["config", "user.email", "test@example.com"], cwd=path)
    _git(["config", "user.name", "Test"], cwd=path)
    # Create an initial commit so HEAD is valid.
    (path / "README.md").write_text("# test repo\n")
    _git(["add", "README.md"], cwd=path)
    _git(["commit", "-m", "initial commit"], cwd=path)
    return path


def _make_repo_with_remote(tmp_path: Path) -> tuple[Path, Path]:
    """Create a local repo wired to a local 'remote' (bare clone).

    Returns (working_repo, bare_remote).
    """
    bare = tmp_path / "remote.git"
    bare.mkdir()
    _git(["init", "--bare", "-b", "main"], cwd=bare)

    repo = tmp_path / "repo"
    _make_repo(repo)
    _git(["remote", "add", "origin", str(bare)], cwd=repo)
    _git(["push", "-u", "origin", "main"], cwd=repo)
    return repo, bare


# ---------------------------------------------------------------------------
# ensure_initialized — creates orphan branch
# ---------------------------------------------------------------------------

class TestEnsureInitialized:
    def test_creates_worktree(self, tmp_path: Path) -> None:
        repo, _bare = _make_repo_with_remote(tmp_path)
        wt = tmp_path / "wt"
        store = MemoryStore(repo, worktree_path=wt)

        store.ensure_initialized()

        assert wt.exists()
        assert (wt / ".gitkeep").exists()

    def test_idempotent_second_call(self, tmp_path: Path) -> None:
        repo, _bare = _make_repo_with_remote(tmp_path)
        wt = tmp_path / "wt"
        store = MemoryStore(repo, worktree_path=wt)

        store.ensure_initialized()
        store.ensure_initialized()  # should not raise

        assert wt.exists()

    def test_attaches_existing_remote_branch(self, tmp_path: Path) -> None:
        """If guardian-memory already exists on origin, it is fetched+attached."""
        repo, bare = _make_repo_with_remote(tmp_path)
        wt1 = tmp_path / "wt1"
        store1 = MemoryStore(repo, worktree_path=wt1)
        store1.ensure_initialized()
        store1.write("hello.txt", "world")
        store1.commit_and_push("add hello", push=True)

        # Fresh store simulating a second CI run.
        wt2 = tmp_path / "wt2"
        store2 = MemoryStore(repo, worktree_path=wt2)
        store2.ensure_initialized()

        assert store2.exists("hello.txt")


# ---------------------------------------------------------------------------
# Guard: read before initialize
# ---------------------------------------------------------------------------

class TestReadGuard:
    def test_raises_before_initialize(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path / "repo")
        store = MemoryStore(repo, worktree_path=tmp_path / "wt")

        with pytest.raises(MemoryNotInitialized):
            store.read("anything.txt")

    def test_exists_raises_before_initialize(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path / "repo")
        store = MemoryStore(repo, worktree_path=tmp_path / "wt")

        with pytest.raises(MemoryNotInitialized):
            store.exists("anything.txt")


# ---------------------------------------------------------------------------
# Read / write / exists / list
# ---------------------------------------------------------------------------

class TestReadWrite:
    def _initialized_store(self, tmp_path: Path) -> MemoryStore:
        repo, _ = _make_repo_with_remote(tmp_path)
        wt = tmp_path / "wt"
        store = MemoryStore(repo, worktree_path=wt)
        store.ensure_initialized()
        return store

    def test_write_then_read_roundtrip(self, tmp_path: Path) -> None:
        store = self._initialized_store(tmp_path)
        store.write("journal/entry.md", "# Entry\nHello.")
        assert store.read("journal/entry.md") == "# Entry\nHello."

    def test_read_missing_raises(self, tmp_path: Path) -> None:
        store = self._initialized_store(tmp_path)
        with pytest.raises(FileNotFoundError):
            store.read("does-not-exist.txt")

    def test_exists_true_and_false(self, tmp_path: Path) -> None:
        store = self._initialized_store(tmp_path)
        store.write("present.txt", "yes")
        assert store.exists("present.txt") is True
        assert store.exists("absent.txt") is False

    def test_write_json_and_read_json(self, tmp_path: Path) -> None:
        store = self._initialized_store(tmp_path)
        obj = {"key": "value", "count": 42}
        store.write_json("data.json", obj)
        result = store.read_json("data.json")
        assert result == obj

    def test_list_empty_prefix(self, tmp_path: Path) -> None:
        store = self._initialized_store(tmp_path)
        store.write("a.txt", "a")
        store.write("subdir/b.txt", "b")
        files = store.list()
        assert "a.txt" in files
        assert "subdir/b.txt" in files

    def test_list_with_prefix(self, tmp_path: Path) -> None:
        store = self._initialized_store(tmp_path)
        store.write("journal/2026-01-01.md", "j1")
        store.write("journal/2026-01-02.md", "j2")
        store.write("sagas/overhaul.md", "s1")
        journal_files = store.list("journal")
        assert all(f.startswith("journal/") for f in journal_files)
        assert len(journal_files) == 2

    def test_list_missing_prefix_returns_empty(self, tmp_path: Path) -> None:
        store = self._initialized_store(tmp_path)
        assert store.list("nonexistent-dir") == []


# ---------------------------------------------------------------------------
# commit_and_push
# ---------------------------------------------------------------------------

class TestCommitAndPush:
    def test_commit_persists_across_stores(self, tmp_path: Path) -> None:
        repo, _ = _make_repo_with_remote(tmp_path)

        wt1 = tmp_path / "wt1"
        s1 = MemoryStore(repo, worktree_path=wt1)
        s1.ensure_initialized()
        s1.write("note.txt", "persistent")
        s1.commit_and_push("add note", push=True)

        # Verify on a second store instance (same worktree).
        wt2 = tmp_path / "wt2"
        s2 = MemoryStore(repo, worktree_path=wt2)
        s2.ensure_initialized()
        assert s2.read("note.txt") == "persistent"

    def test_existing_remote_branch_pushes_from_fresh_clone(self, tmp_path: Path) -> None:
        repo, bare = _make_repo_with_remote(tmp_path)

        wt1 = tmp_path / "wt1"
        s1 = MemoryStore(repo, worktree_path=wt1)
        s1.ensure_initialized()
        s1.write("first.txt", "seed")
        s1.commit_and_push("seed memory", push=True)

        fresh = tmp_path / "fresh-clone"
        _git(["clone", str(bare), str(fresh)], cwd=tmp_path)
        _git(["config", "user.email", "test@example.com"], cwd=fresh)
        _git(["config", "user.name", "Test"], cwd=fresh)

        wt2 = tmp_path / "wt2"
        s2 = MemoryStore(fresh, worktree_path=wt2)
        s2.ensure_initialized()
        s2.write("second.txt", "from fresh clone")
        s2.commit_and_push("persist from fresh clone", push=True)

        verify = tmp_path / "verify-memory"
        _git(["clone", "--branch", "guardian-memory", str(bare), str(verify)], cwd=tmp_path)
        assert (verify / "second.txt").read_text(encoding="utf-8") == "from fresh clone"

    def test_push_failure_raises_when_push_requested(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path / "repo")
        wt = tmp_path / "wt"
        store = MemoryStore(repo, worktree_path=wt)
        store.ensure_initialized()
        store.write("note.txt", "local only")

        with pytest.raises(subprocess.CalledProcessError):
            store.commit_and_push("attempt push without origin", push=True)

    def test_empty_commit_is_noop(self, tmp_path: Path) -> None:
        repo, _ = _make_repo_with_remote(tmp_path)
        wt = tmp_path / "wt"
        store = MemoryStore(repo, worktree_path=wt)
        store.ensure_initialized()
        # No writes — commit_and_push should not raise.
        store.commit_and_push("empty commit", push=False)


# ---------------------------------------------------------------------------
# Session context manager
# ---------------------------------------------------------------------------

class TestSession:
    def test_session_commits_on_exit(self, tmp_path: Path) -> None:
        repo, _ = _make_repo_with_remote(tmp_path)
        wt = tmp_path / "wt"
        store = MemoryStore(repo, worktree_path=wt)
        store.ensure_initialized()

        with store.session("batch write", push=False) as s:
            s.write("a.txt", "alpha")
            s.write("b.txt", "beta")

        # After context exit the files should be committed (readable from git log).
        log = _git(["log", "--oneline", "-1"], cwd=wt)
        assert "batch write" in log

    def test_session_yields_same_store(self, tmp_path: Path) -> None:
        repo, _ = _make_repo_with_remote(tmp_path)
        wt = tmp_path / "wt"
        store = MemoryStore(repo, worktree_path=wt)
        store.ensure_initialized()

        with store.session("check yield", push=False) as s:
            assert s is store
