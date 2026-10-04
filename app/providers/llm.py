from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import Protocol

from app.schemas import TokenUsage


class ProviderError(Exception):
    """An expected upstream provider failure."""


@dataclass(frozen=True)
class Generation:
    reply: str
    provider: str
    model: str
    usage: TokenUsage = field(default_factory=TokenUsage)


# A stream yields text deltas, then exactly one final Generation with the full reply.
StreamEvent = str | Generation


class LLMProvider(Protocol):
    async def generate(self, message: str) -> Generation: ...

    def stream(self, message: str) -> AsyncGenerator[StreamEvent, None]: ...

    async def aclose(self) -> None: ...


class MockProvider:
    async def aclose(self) -> None:
        """The local mock owns no external resources."""

    async def generate(self, message: str) -> Generation:
        return Generation(
            reply=f"[Mock response — no LLM called] Received: {message}",
            provider="mock",
            model="mock-v1",
        )

    async def stream(self, message: str) -> AsyncGenerator[StreamEvent, None]:
        result = await self.generate(message)
        for index, word in enumerate(result.reply.split(" ")):
            yield word if index == 0 else f" {word}"
        yield result
