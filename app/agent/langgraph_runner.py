"""Adapts any compiled LangGraph graph to the Workflow contract."""

from collections.abc import AsyncGenerator, Awaitable, Callable, Mapping
from contextlib import aclosing
from functools import wraps
from typing import Any

from langgraph.config import get_stream_writer
from langgraph.graph.state import CompiledStateGraph
from langgraph.runtime import Runtime

from app.agent.workflow import RunContext, WorkflowInput
from app.providers.llm import Generation, ProviderError, StreamEvent

_TEXT = "text"

Node = Callable[[Any, Runtime[RunContext]], Awaitable[Mapping[str, Any]]]


def traced_node(name: str, node: Node) -> Node:
    """Wrap a node so it is traced and logged as `node.<name>` with its state in and out.

    Input and output reach the tracer only when content capture is enabled.
    """

    @wraps(node)
    async def wrapper(state: Any, runtime: Runtime[RunContext]) -> Mapping[str, Any]:
        with runtime.context.trace(f"node.{name}") as span:
            span.set_input(dict(state))
            update = await node(state, runtime)
            span.set_output(dict(update or {}))
            return update

    return wrapper


def emit_text(text: str) -> None:
    """Stream a chunk of reply text to the client from inside any node.

    Outside a streaming run LangGraph's writer is a no-op, so nodes need not check.
    """
    get_stream_writer()({"type": _TEXT, "text": text})


class LangGraphWorkflow:
    """Runs a graph; the graph module supplies how input and final state are mapped."""

    def __init__(
        self,
        graph: CompiledStateGraph,
        to_state: Callable[[WorkflowInput], Mapping[str, Any]],
        to_generation: Callable[[Mapping[str, Any]], Generation],
    ):
        self.graph = graph
        self.to_state = to_state
        self.to_generation = to_generation

    @staticmethod
    def _config(ctx: RunContext) -> dict[str, Any] | None:
        return {"configurable": {"thread_id": ctx.thread_id}} if ctx.thread_id else None

    async def run(self, request: WorkflowInput, ctx: RunContext) -> Generation:
        state = await self.graph.ainvoke(
            self.to_state(request), config=self._config(ctx), context=ctx
        )
        return self.to_generation(state)

    async def stream(
        self, request: WorkflowInput, ctx: RunContext
    ) -> AsyncGenerator[StreamEvent, None]:
        final: Mapping[str, Any] | None = None
        events = self.graph.astream(
            self.to_state(request),
            config=self._config(ctx),
            context=ctx,
            stream_mode=["custom", "values"],
        )
        async with aclosing(events):
            async for mode, data in events:
                if mode == "custom" and isinstance(data, dict) and data.get("type") == _TEXT:
                    yield data["text"]
                elif mode == "values":
                    final = data
        if final is None:
            raise ProviderError("Workflow produced no result.")
        yield self.to_generation(final)
