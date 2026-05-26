"""LLM provider adapters for NorthStarGuardian.

Domain modules depend on the small ``generate`` interface here instead of raw
provider SDK clients. This keeps agent logic stable while provider details live
at the boundary.
"""

from __future__ import annotations

from typing import Any, Protocol

from anthropic import Anthropic


class LLMClient(Protocol):
    """Minimal text-generation interface used by Guardian domain modules."""

    def generate(
        self,
        *,
        system: str,
        user: str,
        model: str,
        max_tokens: int = 4096,
    ) -> str:
        """Return generated text for a system prompt and user prompt."""


class AnthropicLLMClient:
    """Anthropic-backed implementation of :class:`LLMClient`."""

    def __init__(self, *, api_key: str, client: Anthropic | None = None) -> None:
        self._client = client or Anthropic(api_key=api_key)

    def generate(
        self,
        *,
        system: str,
        user: str,
        model: str,
        max_tokens: int = 4096,
    ) -> str:
        """Call Anthropic Messages and return concatenated text blocks."""
        message = self._client.messages.create(
            model=model,
            system=system,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": user}],
        )
        return _extract_text(message)


def _extract_text(message: Any) -> str:
    """Extract text from provider response content blocks."""
    chunks: list[str] = []
    for block in getattr(message, "content", []):
        text = getattr(block, "text", None)
        if text is not None:
            chunks.append(str(text))
            continue
        if isinstance(block, dict) and block.get("type") == "text":
            chunks.append(str(block.get("text", "")))
    return "\n".join(chunk for chunk in chunks if chunk).strip()
