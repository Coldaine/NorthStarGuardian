"""Tests for guardian.memory repo-native storage."""

from __future__ import annotations

from pathlib import Path

import pytest

from guardian.memory import MemoryNotInitialized, MemoryStore


def _make_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / "README.md").write_text("# test repo\n", encoding="utf-8")
    return path


class TestEnsureInitialized:
    def test_creates_guardian_directory_in_normal_checkout(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path / "repo")
        store = MemoryStore(repo)

        store.ensure_initialized()

        assert (repo / ".github" / "guardian").is_dir()

    def test_idempotent_second_call(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path / "repo")
        store = MemoryStore(repo)

        store.ensure_initialized()
        store.ensure_initialized()

        assert (repo / ".github" / "guardian").is_dir()


class TestReadGuard:
    def test_read_raises_before_initialize(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path / "repo")
        store = MemoryStore(repo)

        with pytest.raises(MemoryNotInitialized):
            store.read("anything.txt")

    def test_exists_raises_before_initialize(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path / "repo")
        store = MemoryStore(repo)

        with pytest.raises(MemoryNotInitialized):
            store.exists("anything.txt")


class TestReadWrite:
    def _initialized_store(self, tmp_path: Path) -> tuple[Path, MemoryStore]:
        repo = _make_repo(tmp_path / "repo")
        store = MemoryStore(repo)
        store.ensure_initialized()
        return repo, store

    def test_write_then_read_roundtrip(self, tmp_path: Path) -> None:
        repo, store = self._initialized_store(tmp_path)

        store.write("memory/journal/entry.md", "# Entry\nHello.")

        assert store.read("memory/journal/entry.md") == "# Entry\nHello."
        assert (repo / ".github" / "guardian" / "memory" / "journal" / "entry.md").exists()

    def test_read_missing_raises(self, tmp_path: Path) -> None:
        _repo, store = self._initialized_store(tmp_path)

        with pytest.raises(FileNotFoundError):
            store.read("does-not-exist.txt")

    def test_exists_true_and_false(self, tmp_path: Path) -> None:
        _repo, store = self._initialized_store(tmp_path)

        store.write("present.txt", "yes")

        assert store.exists("present.txt") is True
        assert store.exists("absent.txt") is False

    def test_write_json_and_read_json(self, tmp_path: Path) -> None:
        _repo, store = self._initialized_store(tmp_path)
        obj = {"key": "value", "count": 42}

        store.write_json("data.json", obj)

        assert store.read_json("data.json") == obj

    def test_list_empty_prefix(self, tmp_path: Path) -> None:
        _repo, store = self._initialized_store(tmp_path)

        store.write("a.txt", "a")
        store.write("subdir/b.txt", "b")

        assert store.list() == ["a.txt", "subdir/b.txt"]

    def test_list_with_prefix(self, tmp_path: Path) -> None:
        _repo, store = self._initialized_store(tmp_path)

        store.write("memory/journal/2026-01-01.md", "j1")
        store.write("memory/journal/2026-01-02.md", "j2")
        store.write("memory/sagas/overhaul.md", "s1")

        journal_files = store.list("memory/journal")

        assert all(f.startswith("memory/journal/") for f in journal_files)
        assert len(journal_files) == 2

    def test_list_missing_prefix_returns_empty(self, tmp_path: Path) -> None:
        _repo, store = self._initialized_store(tmp_path)

        assert store.list("nonexistent-dir") == []

    def test_rejects_path_traversal(self, tmp_path: Path) -> None:
        _repo, store = self._initialized_store(tmp_path)

        with pytest.raises(ValueError, match="outside Guardian storage"):
            store.write("../escape.txt", "no")


class TestCommitAndPush:
    def test_commit_and_push_is_noop_for_repo_native_store(self, tmp_path: Path) -> None:
        repo, store = TestReadWrite()._initialized_store(tmp_path)

        store.write("note.txt", "persistent")
        store.commit_and_push("add note", push=True)

        assert store.read("note.txt") == "persistent"

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
        _repo, store = TestReadWrite()._initialized_store(tmp_path)

        store.commit_and_push("empty commit", push=False)


class TestSession:
    def test_session_yields_same_store(self, tmp_path: Path) -> None:
        _repo, store = TestReadWrite()._initialized_store(tmp_path)

        with store.session("check yield", push=False) as s:
            assert s is store

    def test_session_keeps_written_files(self, tmp_path: Path) -> None:
        _repo, store = TestReadWrite()._initialized_store(tmp_path)

        with store.session("batch write", push=False) as s:
            s.write("a.txt", "alpha")
            s.write("b.txt", "beta")

        assert store.read("a.txt") == "alpha"
        assert store.read("b.txt") == "beta"
