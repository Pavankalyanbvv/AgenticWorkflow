"""Conversation and run records behind an interface the agent service depends on."""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal, Protocol

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import AgentRun, Conversation, Message
from app.providers.llm import Generation


class ConversationNotFoundError(Exception):
    """The requested conversation does not exist."""


@dataclass(frozen=True)
class RunRecord:
    run_id: uuid.UUID
    conversation_id: uuid.UUID


FailureStatus = Literal["failed", "cancelled"]


class ConversationStore(Protocol):
    async def start_run(
        self,
        conversation_id: uuid.UUID | None,
        message: str,
        request_id: str | None,
        trace_id: str | None,
    ) -> RunRecord:
        """Create or load the conversation, save the user message and a running run."""
        ...

    async def complete_run(self, run: RunRecord, result: Generation) -> None:
        """Save the assistant reply and mark the run completed."""
        ...

    async def fail_run(self, run: RunRecord, status: FailureStatus, error_type: str) -> None:
        """Mark the run failed or cancelled."""
        ...


class SqlConversationStore:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]):
        self.sessions = sessions

    async def start_run(
        self,
        conversation_id: uuid.UUID | None,
        message: str,
        request_id: str | None,
        trace_id: str | None,
    ) -> RunRecord:
        async with self.sessions.begin() as session:
            if conversation_id is None:
                conversation = Conversation(id=uuid.uuid4())
                session.add(conversation)
                await session.flush()
            else:
                found = await session.execute(
                    update(Conversation)
                    .where(Conversation.id == conversation_id)
                    .values(updated_at=func.now())
                    .returning(Conversation.id)
                )
                if found.scalar_one_or_none() is None:
                    raise ConversationNotFoundError
            run = RunRecord(run_id=uuid.uuid4(), conversation_id=conversation_id or conversation.id)
            session.add_all(
                [
                    Message(
                        id=uuid.uuid4(),
                        conversation_id=run.conversation_id,
                        role="user",
                        content=message,
                    ),
                    AgentRun(
                        id=run.run_id,
                        conversation_id=run.conversation_id,
                        request_id=request_id,
                        status="running",
                        trace_id=trace_id,
                    ),
                ]
            )
        return run

    async def complete_run(self, run: RunRecord, result: Generation) -> None:
        async with self.sessions.begin() as session:
            session.add(
                Message(
                    id=uuid.uuid4(),
                    conversation_id=run.conversation_id,
                    role="assistant",
                    content=result.reply,
                )
            )
            await session.execute(
                update(AgentRun)
                .where(AgentRun.id == run.run_id)
                .values(
                    status="completed",
                    provider=result.provider,
                    model=result.model,
                    input_tokens=result.usage.input_tokens,
                    output_tokens=result.usage.output_tokens,
                    finished_at=func.now(),
                )
            )

    async def fail_run(self, run: RunRecord, status: FailureStatus, error_type: str) -> None:
        async with self.sessions.begin() as session:
            await session.execute(
                update(AgentRun)
                .where(AgentRun.id == run.run_id)
                .values(status=status, error_type=error_type, finished_at=func.now())
            )

    async def ping(self) -> None:
        async with self.sessions() as session:
            await session.execute(select(1))


@dataclass
class InMemoryConversationStore:
    """For tests and local experiments; nothing survives a restart."""

    conversations: set[uuid.UUID] = field(default_factory=set)
    messages: list[dict] = field(default_factory=list)
    runs: dict[uuid.UUID, dict] = field(default_factory=dict)

    async def start_run(
        self,
        conversation_id: uuid.UUID | None,
        message: str,
        request_id: str | None,
        trace_id: str | None,
    ) -> RunRecord:
        if conversation_id is None:
            conversation_id = uuid.uuid4()
            self.conversations.add(conversation_id)
        elif conversation_id not in self.conversations:
            raise ConversationNotFoundError
        run = RunRecord(run_id=uuid.uuid4(), conversation_id=conversation_id)
        self.messages.append(
            {"conversation_id": conversation_id, "role": "user", "content": message}
        )
        self.runs[run.run_id] = {
            "conversation_id": conversation_id,
            "request_id": request_id,
            "status": "running",
            "trace_id": trace_id,
            "started_at": datetime.now(UTC),
        }
        return run

    async def complete_run(self, run: RunRecord, result: Generation) -> None:
        self.messages.append(
            {"conversation_id": run.conversation_id, "role": "assistant", "content": result.reply}
        )
        self.runs[run.run_id].update(status="completed", model=result.model)

    async def fail_run(self, run: RunRecord, status: FailureStatus, error_type: str) -> None:
        self.runs[run.run_id].update(status=status, error_type=error_type)

    async def ping(self) -> None:
        """Always available."""
