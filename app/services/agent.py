import asyncio
from time import perf_counter

import structlog

from app.providers.llm import Generation, LLMProvider

logger = structlog.get_logger(__name__)


class AgentService:
    """Layer 1: a single provider call; graph orchestration comes later."""

    def __init__(self, provider: LLMProvider, timeout_seconds: float):
        self.provider = provider
        self.timeout_seconds = timeout_seconds

    async def respond(self, message: str) -> Generation:
        started = perf_counter()
        logger.info("agent.started")
        try:
            async with asyncio.timeout(self.timeout_seconds):
                result = await self.provider.generate(message)
        except Exception as exc:
            logger.warning("agent.failed", error_type=type(exc).__name__)
            raise
        logger.info(
            "agent.completed",
            duration_ms=round((perf_counter() - started) * 1000, 2),
            provider=result.provider,
            model=result.model,
            input_tokens=result.usage.input_tokens,
            output_tokens=result.usage.output_tokens,
        )
        return result
