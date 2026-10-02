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


class LLMProvider(Protocol):
    async def generate(self, message: str) -> Generation: ...


class MockProvider:
    async def generate(self, message: str) -> Generation:
        return Generation(
            reply=f"[Mock response — no LLM called] Received: {message}",
            provider="mock",
            model="mock-v1",
        )
