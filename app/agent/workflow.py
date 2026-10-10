"""Stable contracts between the agent service and any workflow implementation.

Graph state, nodes and edges stay private to each workflow; the rest of the app depends
only on these types. Extend WorkflowInput and RunContext with optional fields only.
"""

from collections.abc import AsyncGenerator, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from time import perf_counter
from typing import Protocol

import structlog

from app.observability import Span
from app.providers.llm import Generation, StreamEvent

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class WorkflowInput:
    """What a request asks the workflow to do."""

    message: str


@dataclass(frozen=True)
class RunContext:
    """Per-request services a workflow may use; never holds graph state."""

    request_id: str | None = None
    streaming: bool = False
    span: Span = field(default_factory=Span)
    # Checkpoint thread for this run; currently one thread per conversation.
    thread_id: str | None = None

    @contextmanager
    def trace(self, name: str) -> Iterator[Span]:
        """Trace and log a workflow step as a child of the run.

        Logs carry only the step name, mode, timing and error type, never state content.
        """
        started = perf_counter()
        logger.info("node.started", node=name, streaming=self.streaming)
        try:
            with self.span.child(name) as span:
                yield span
        except BaseException as exc:
            # BaseException also records cancellations, e.g. when the request times out.
            logger.warning(
                "node.failed",
                node=name,
                error_type=type(exc).__name__,
                duration_ms=round((perf_counter() - started) * 1000, 2),
            )
            raise
        logger.info(
            "node.completed",
            node=name,
            duration_ms=round((perf_counter() - started) * 1000, 2),
        )


class Workflow(Protocol):
    async def run(self, request: WorkflowInput, ctx: RunContext) -> Generation: ...

    def stream(
        self, request: WorkflowInput, ctx: RunContext
    ) -> AsyncGenerator[StreamEvent, None]: ...
