import asyncio
import uuid
from collections.abc import AsyncGenerator
from contextlib import aclosing
from dataclasses import dataclass
from time import perf_counter

import structlog
from structlog.contextvars import bind_contextvars, get_contextvars

from app.agent.workflow import RunContext, Workflow, WorkflowInput
from app.db.store import ConversationStore, RunRecord
from app.observability import Span, Tracer
from app.providers.llm import Generation

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class AgentReply:
    """A completed reply and the conversation it belongs to."""

    generation: Generation
    conversation_id: uuid.UUID


# A stream yields text deltas, then exactly one final AgentReply.
AgentStreamEvent = str | AgentReply


class AgentService:
    """Runs a workflow with a timeout, a root trace span, run records and structured logs."""

    def __init__(
        self, workflow: Workflow, tracer: Tracer, store: ConversationStore, timeout_seconds: float
    ):
        self.workflow = workflow
        self.tracer = tracer
        self.store = store
        self.timeout_seconds = timeout_seconds

    async def _start_run(
        self, message: str, conversation_id: uuid.UUID | None, streaming: bool
    ) -> tuple[RunContext, RunRecord]:
        request_id = get_contextvars().get("request_id")
        span = self.tracer.start_run(
            name="agent.run",
            input=message,
            metadata={"request_id": request_id, "streaming": streaming},
        )
        if span.trace_id:
            # Correlate later logs for this request with the trace.
            bind_contextvars(trace_id=span.trace_id)
        try:
            run = await self.store.start_run(conversation_id, message, request_id, span.trace_id)
        except BaseException as exc:
            span.fail(exc)
            span.end()
            if isinstance(exc, Exception):
                logger.warning("agent.failed", error_type=type(exc).__name__)
            raise
        bind_contextvars(conversation_id=str(run.conversation_id), run_id=str(run.run_id))
        logger.info("agent.started", streaming=streaming)
        # One checkpoint thread per conversation; the graph resets per-turn state itself.
        ctx = RunContext(
            request_id=request_id,
            streaming=streaming,
            span=span,
            thread_id=str(run.conversation_id),
        )
        return ctx, run

    async def _fail(self, span: Span, run: RunRecord, exc: BaseException) -> None:
        span.fail(exc)
        # Exceptions are failures; cancellations (disconnects, shutdown) are not errors.
        failed = isinstance(exc, Exception)
        if failed:
            logger.warning("agent.failed", error_type=type(exc).__name__)
        try:
            await self.store.fail_run(run, "failed" if failed else "cancelled", type(exc).__name__)
        except Exception as store_exc:
            logger.error("run.record_failed", error_type=type(store_exc).__name__)

    async def respond(self, message: str, conversation_id: uuid.UUID | None = None) -> AgentReply:
        started = perf_counter()
        ctx, run = await self._start_run(message, conversation_id, streaming=False)
        try:
            async with asyncio.timeout(self.timeout_seconds):
                result = await self.workflow.run(WorkflowInput(message=message), ctx)
            await self.store.complete_run(run, result)
            ctx.span.set_output(result.reply)
        except BaseException as exc:
            await self._fail(ctx.span, run, exc)
            raise
        finally:
            ctx.span.end()
        self._log_completed(result, started)
        return AgentReply(generation=result, conversation_id=run.conversation_id)

    async def stream(
        self, message: str, conversation_id: uuid.UUID | None = None
    ) -> AsyncGenerator[AgentStreamEvent, None]:
        started = perf_counter()
        ctx, run = await self._start_run(message, conversation_id, streaming=True)
        loop = asyncio.get_running_loop()
        # One deadline for the whole stream, checked per chunk: a timeout context cannot
        # span yields because the response body may be consumed in a different task.
        deadline = loop.time() + self.timeout_seconds
        events = self.workflow.stream(WorkflowInput(message=message), ctx)
        completed = False
        try:
            async with aclosing(events):
                while True:
                    remaining = deadline - loop.time()
                    if remaining <= 0:
                        raise TimeoutError("Workflow stream exceeded the request timeout.")
                    try:
                        event = await asyncio.wait_for(anext(events), remaining)
                    except StopAsyncIteration:
                        break
                    if isinstance(event, Generation):
                        await self.store.complete_run(run, event)
                        completed = True
                        ctx.span.set_output(event.reply)
                        self._log_completed(event, started)
                        yield AgentReply(generation=event, conversation_id=run.conversation_id)
                    else:
                        yield event
        except BaseException as exc:
            # A disconnect after the reply was saved must not overwrite the completed run.
            if not completed:
                await self._fail(ctx.span, run, exc)
            raise
        finally:
            ctx.span.end()

    def _log_completed(self, result: Generation, started: float) -> None:
        logger.info(
            "agent.completed",
            duration_ms=round((perf_counter() - started) * 1000, 2),
            provider=result.provider,
            model=result.model,
            input_tokens=result.usage.input_tokens,
            output_tokens=result.usage.output_tokens,
        )
