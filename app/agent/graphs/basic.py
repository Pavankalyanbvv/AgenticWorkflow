"""Basic graph: START → generate → validate_response → END.

State, nodes and edges are private to this module. Change them freely; keep
to_state/to_generation returning the shared contract types. State is checkpointed,
so keep it to plain values (str, int, list, dict).
"""

from contextlib import aclosing
from dataclasses import asdict
from typing import Any, TypedDict

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from app.agent.langgraph_runner import LangGraphWorkflow, emit_text, traced_node
from app.agent.workflow import RunContext, WorkflowInput
from app.providers.llm import Generation, LLMProvider, ProviderError
from app.schemas import TokenUsage


class State(TypedDict, total=False):
    message: str
    reply: str
    # Generation as a plain dict (see to_generation).
    generation: dict[str, Any] | None


def to_state(request: WorkflowInput) -> State:
    # A conversation's thread keeps earlier state; reset per-turn fields so a run never
    # sees the previous turn's reply (no conversation memory yet).
    return {"message": request.message, "reply": "", "generation": None}


def to_generation(state: State) -> Generation:
    data = dict(state["generation"])
    return Generation(**{**data, "usage": TokenUsage(**data["usage"])})


def build(provider: LLMProvider, checkpointer: BaseCheckpointSaver) -> LangGraphWorkflow:
    async def generate(state: State, runtime: Runtime[RunContext]) -> State:
        if not runtime.context.streaming:
            result = await provider.generate(state["message"])
        else:
            result = None
            async with aclosing(provider.stream(state["message"])) as events:
                async for event in events:
                    if isinstance(event, Generation):
                        result = event
                    else:
                        emit_text(event)
            if result is None:
                raise ProviderError("Model stream ended without a result.")
        generation = {**asdict(result), "usage": result.usage.model_dump()}
        return {"reply": result.reply, "generation": generation}

    async def validate_response(state: State, runtime: Runtime[RunContext]) -> State:
        if not state.get("reply", "").strip():
            raise ProviderError("Model returned an empty reply.")
        return {}

    # traced_node adds the node.<name> span, logs and state in/out to every node.
    graph = (
        StateGraph(State, context_schema=RunContext)
        .add_node("generate", traced_node("generate", generate))
        .add_node("validate_response", traced_node("validate_response", validate_response))
        .add_edge(START, "generate")
        .add_edge("generate", "validate_response")
        .add_edge("validate_response", END)
        .compile(checkpointer=checkpointer, name="basic")
    )
    return LangGraphWorkflow(graph, to_state, to_generation)
