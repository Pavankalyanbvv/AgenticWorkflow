"""Tracing interface used by the agent and providers; the only module importing Langfuse."""

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

from app.config import Settings
from app.providers.llm import Generation


class Span:
    """A traced unit of work. This base class is the no-op used when tracing is off."""

    trace_id: str | None = None

    @contextmanager
    def child(self, name: str) -> Iterator["Span"]:
        """Trace a nested step; observations started inside it nest under it."""
        yield self

    def set_input(self, input: Any) -> None:
        """Record what the step received; dropped unless content capture is enabled."""

    def set_output(self, output: Any) -> None:
        """Record the result; dropped unless content capture is enabled."""

    def fail(self, exc: BaseException) -> None:
        """Mark the span as failed, recording only the exception type."""

    def end(self) -> None:
        """Finish the span."""


class GenerationSpan(Span):
    """A traced model call."""

    def first_token(self) -> None:
        """Record the time the first streamed chunk arrived."""

    def complete(self, result: Generation) -> None:
        """Record the model, usage and (if captured) the reply."""


class Tracer:
    """Creates spans. This base class is the no-op used when tracing is off."""

    def start_run(self, name: str, input: Any, metadata: dict[str, Any]) -> Span:
        return Span()

    def start_generation(self, name: str, input: Any, metadata: dict[str, Any]) -> GenerationSpan:
        return GenerationSpan()

    async def shutdown(self) -> None:
        """Flush buffered spans."""


class _LangfuseSpan(GenerationSpan):
    def __init__(self, observation: Any, capture_content: bool):
        self._observation = observation
        self._capture_content = capture_content
        self.trace_id = observation.trace_id

    @contextmanager
    def child(self, name: str) -> Iterator[Span]:
        # "Current" spans are safe here: a child block never spans a yield across tasks.
        with self._observation.start_as_current_observation(name=name) as observation:
            span = _LangfuseSpan(observation, self._capture_content)
            try:
                yield span
            except BaseException as exc:
                span.fail(exc)
                raise

    def set_input(self, input: Any) -> None:
        if self._capture_content:
            self._observation.update(input=input)

    def set_output(self, output: Any) -> None:
        if self._capture_content:
            self._observation.update(output=output)

    def fail(self, exc: BaseException) -> None:
        # Exception messages may contain private data; record only the type.
        self._observation.update(level="ERROR", status_message=type(exc).__name__)

    def end(self) -> None:
        self._observation.end()

    def first_token(self) -> None:
        self._observation.update(completion_start_time=datetime.now(UTC))

    def complete(self, result: Generation) -> None:
        usage = {
            key: value
            for key, value in (
                ("input", result.usage.input_tokens),
                ("output", result.usage.output_tokens),
            )
            if value is not None
        }
        self._observation.update(
            model=result.model,
            output=result.reply if self._capture_content else None,
            usage_details=usage or None,
            metadata={"provider": result.provider},
        )


class LangfuseTracer(Tracer):
    def __init__(self, settings: Settings):
        from langfuse import Langfuse

        self._capture_content = settings.langfuse_capture_content
        self._client = Langfuse(
            public_key=settings.langfuse_public_key.strip(),
            secret_key=settings.langfuse_secret_key.get_secret_value().strip(),
            base_url=settings.langfuse_base_url,
            environment=settings.environment,
        )

    def _start(self, name: str, as_type: str, input: Any, metadata: dict[str, Any]):
        # Not made "current": a run or stream may finish in a different task, and
        # OpenTelemetry context cannot be detached across tasks. The parent is
        # whatever span is current when this is called (e.g. a graph node).
        observation = self._client.start_observation(
            name=name,
            as_type=as_type,
            input=input if self._capture_content else None,
            metadata=metadata,
        )
        return _LangfuseSpan(observation, self._capture_content)

    def start_run(self, name: str, input: Any, metadata: dict[str, Any]) -> Span:
        return self._start(name, "agent", input, metadata)

    def start_generation(self, name: str, input: Any, metadata: dict[str, Any]) -> GenerationSpan:
        return self._start(name, "generation", input, metadata)

    async def shutdown(self) -> None:
        # Flush only: the SDK's client is shared per process and shuts itself down at exit.
        # Calling its shutdown() here would stop workers that a later app instance (tests,
        # scripts) still needs, and that app's shutdown would then wait forever.
        await asyncio.to_thread(self._client.flush)


def create_tracer(settings: Settings) -> Tracer:
    """Langfuse when both keys are configured, otherwise a no-op tracer."""
    return LangfuseTracer(settings) if settings.langfuse_enabled else Tracer()
