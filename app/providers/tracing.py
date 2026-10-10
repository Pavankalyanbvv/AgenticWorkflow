from collections.abc import AsyncGenerator
from contextlib import aclosing
from datetime import UTC, datetime

import structlog
from langfuse import Langfuse, LangfuseGeneration
from structlog.contextvars import bind_contextvars, get_contextvars

from app.config import Settings
from app.providers.llm import Generation, LLMProvider, StreamEvent

logger = structlog.get_logger(__name__)


def create_langfuse(settings: Settings) -> Langfuse | None:
    """Return a Langfuse client when both keys are configured, otherwise None."""
    if not settings.langfuse_enabled:
        return None
    return Langfuse(
        public_key=settings.langfuse_public_key.strip(),
        secret_key=settings.langfuse_secret_key.get_secret_value().strip(),
        base_url=settings.langfuse_base_url,
        environment=settings.environment,
    )


class TracedProvider:
    """Records one Langfuse generation per model call around any LLMProvider."""

    def __init__(self, inner: LLMProvider, langfuse: Langfuse, capture_content: bool):
        self.inner = inner
        self.langfuse = langfuse
        self.capture_content = capture_content

    async def aclose(self) -> None:
        await self.inner.aclose()

    def _start(self, message: str, streaming: bool) -> LangfuseGeneration:
        request_id = get_contextvars().get("request_id")
        # Spans are started without becoming "current": a stream's body may finish in a
        # different task, and OpenTelemetry context cannot be detached across tasks.
        observation = self.langfuse.start_observation(
            name="llm.stream" if streaming else "llm.generate",
            as_type="generation",
            input=message if self.capture_content else None,
            metadata={"request_id": request_id, "streaming": streaming},
        )
        # Correlate later logs for this request with the trace.
        bind_contextvars(trace_id=observation.trace_id)
        logger.info("llm.traced", trace_id=observation.trace_id)
        return observation

    def _finish(self, observation: LangfuseGeneration, result: Generation) -> None:
        usage = {
            key: value
            for key, value in (
                ("input", result.usage.input_tokens),
                ("output", result.usage.output_tokens),
            )
            if value is not None
        }
        observation.update(
            model=result.model,
            output=result.reply if self.capture_content else None,
            usage_details=usage or None,
            metadata={"provider": result.provider},
        )

    @staticmethod
    def _fail(observation: LangfuseGeneration, exc: BaseException) -> None:
        # Exception messages may contain private data; record only the type.
        observation.update(level="ERROR", status_message=type(exc).__name__)

    async def generate(self, message: str) -> Generation:
        observation = self._start(message, streaming=False)
        try:
            result = await self.inner.generate(message)
            self._finish(observation, result)
            return result
        except BaseException as exc:
            self._fail(observation, exc)
            raise
        finally:
            observation.end()

    async def stream(self, message: str) -> AsyncGenerator[StreamEvent, None]:
        observation = self._start(message, streaming=True)
        first_chunk = True
        try:
            async with aclosing(self.inner.stream(message)) as events:
                async for event in events:
                    if isinstance(event, Generation):
                        self._finish(observation, event)
                    elif first_chunk:
                        # Lets Langfuse report time to first token.
                        observation.update(completion_start_time=datetime.now(UTC))
                        first_chunk = False
                    yield event
        except BaseException as exc:
            self._fail(observation, exc)
            raise
        finally:
            observation.end()
