from langgraph.checkpoint.base import BaseCheckpointSaver

from app.agent.graphs import basic
from app.agent.workflow import Workflow
from app.providers.llm import LLMProvider


def create_workflow(provider: LLMProvider, checkpointer: BaseCheckpointSaver) -> Workflow:
    """Select the workflow; the rest of the app depends only on the Workflow contract."""
    return basic.build(provider, checkpointer)
