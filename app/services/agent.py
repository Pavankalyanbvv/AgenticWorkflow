import asyncio
from collections.abc import AsyncGenerator
from time import perf_counter

import structlog

from app.providers.llm import Generation, LLMProvider, StreamEvent

logger = structlog.get_logger(__name__)


class AgentService:
    """Layer 1: a single provider call; graph orchestration comes later."""

    def __init__(self, provider: LLMProvider, timeout_seconds: float):
        self.provider = provider
        self.timeout_seconds = timeout_seconds

    async def respond(self, message: str) -> Generation:
        started = perf_counter()
        logger.info("agent.started", streaming=False)
        try:
            async with asyncio.timeout(self.timeout_seconds):
                result = await self.provider.generate(message)
        except Exception as exc:
            logger.warning("agent.failed", error_type=type(exc).__name__)
            raise
        self._log_completed(result, started)
        return result

    async def stream(self, message: str) -> AsyncGenerator[StreamEvent, None]:
        started = perf_counter()
        logger.info("agent.started", streaming=True)
        loop = asyncio.get_running_loop()
        # One deadline for the whole stream, checked per chunk: a timeout context cannot
        # span yields because the response body may be consumed in a different task.
        deadline = loop.time() + self.timeout_seconds
        events = self.provider.stream(message)
        try:
            while True:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    raise TimeoutError("Model stream exceeded the request timeout.")
                try:
                    event = await asyncio.wait_for(anext(events), remaining)
                except StopAsyncIteration:
                    break
                if isinstance(event, Generation):
                    self._log_completed(event, started)
                yield event
        except Exception as exc:
            logger.warning("agent.failed", error_type=type(exc).__name__)
            raise
        finally:
            await events.aclose()

    def _log_completed(self, result: Generation, started: float) -> None:
        logger.info(
            "agent.completed",
            duration_ms=round((perf_counter() - started) * 1000, 2),
            provider=result.provider,
            model=result.model,
            input_tokens=result.usage.input_tokens,
            output_tokens=result.usage.output_tokens,
        )
