from collections.abc import AsyncGenerator
from contextlib import aclosing

from structlog.contextvars import get_contextvars

from app.observability import GenerationSpan, Tracer
from app.providers.llm import Generation, LLMProvider, StreamEvent


class TracedProvider:
    """Records one traced generation per model call around any LLMProvider."""

    def __init__(self, inner: LLMProvider, tracer: Tracer):
        self.inner = inner
        self.tracer = tracer

    async def aclose(self) -> None:
        await self.inner.aclose()

    def _start(self, message: str, streaming: bool) -> GenerationSpan:
        return self.tracer.start_generation(
            name="llm.stream" if streaming else "llm.generate",
            input=message,
            metadata={"request_id": get_contextvars().get("request_id"), "streaming": streaming},
        )

    async def generate(self, message: str) -> Generation:
        span = self._start(message, streaming=False)
        try:
            result = await self.inner.generate(message)
            span.complete(result)
            return result
        except BaseException as exc:
            span.fail(exc)
            raise
        finally:
            span.end()

    async def stream(self, message: str) -> AsyncGenerator[StreamEvent, None]:
        span = self._start(message, streaming=True)
        first_chunk = True
        try:
            async with aclosing(self.inner.stream(message)) as events:
                async for event in events:
                    if isinstance(event, Generation):
                        span.complete(event)
                    elif first_chunk:
                        # Lets the tracing backend report time to first token.
                        span.first_token()
                        first_chunk = False
                    yield event
        except BaseException as exc:
            span.fail(exc)
            raise
        finally:
            span.end()
