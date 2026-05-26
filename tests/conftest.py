"""Shared test fixtures for NorthStarGuardian tests."""

from __future__ import annotations

from typing import Any

import pytest


class FakeStore:
    """In-memory stand-in for MemoryStore; no git, no filesystem side-effects.

    Behaves like MemoryStore but stores files in a plain dict so north_star
    tests run fully offline without spinning up a git repository.
    """

    def __init__(self) -> None:
        self._files: dict[str, str] = {}
        self._initialized = True  # FakeStore is always "initialized"

    # ------------------------------------------------------------------
    # MemoryStore-compatible API
    # ------------------------------------------------------------------

    def ensure_initialized(self) -> None:
        pass

    def read(self, path: str) -> str:
        if path not in self._files:
            raise FileNotFoundError(f"fake-store:{path} does not exist")
        return self._files[path]

    def read_json(self, path: str) -> Any:
        import json
        return json.loads(self.read(path))

    def exists(self, path: str) -> bool:
        return path in self._files

    def write(self, path: str, content: str, message: str = "") -> None:
        self._files[path] = content

    def write_json(self, path: str, obj: Any, message: str = "") -> None:
        import json
        self._files[path] = json.dumps(obj, indent=2, default=str)

    def list(self, prefix: str = "") -> list[str]:
        if not prefix:
            return sorted(self._files.keys())
        return sorted(k for k in self._files if k.startswith(prefix))

    def commit_and_push(self, message: str, push: bool = True) -> None:
        pass  # no-op for in-memory store

    # Context manager session
    def session(self, message: str, push: bool = True):
        from contextlib import contextmanager

        @contextmanager
        def _ctx():
            yield self
            self.commit_and_push(message, push=push)

        return _ctx()


@pytest.fixture
def fake_store() -> FakeStore:
    """Return a fresh FakeStore for each test."""
    return FakeStore()
