"""Database resources for one application: the conversation store and graph checkpointer."""

import asyncio

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.store import ConversationStore, InMemoryConversationStore, SqlConversationStore


def sqlalchemy_url(database_url: str) -> str:
    """Select SQLAlchemy's async psycopg driver for a plain postgresql:// URL."""
    for prefix in ("postgresql+psycopg://", "postgresql://", "postgres://"):
        if database_url.startswith(prefix):
            return "postgresql+psycopg://" + database_url.removeprefix(prefix)
    raise ValueError("DATABASE_URL must be a postgresql:// URL.")


def libpq_url(database_url: str) -> str:
    """psycopg itself expects the plain postgresql:// form."""
    return database_url.replace("postgresql+psycopg://", "postgresql://", 1)


class Persistence:
    """Owns the store and checkpointer; opened and closed with the application.

    The checkpointer is available only after open(), inside the running event loop.
    """

    store: ConversationStore
    checkpointer: BaseCheckpointSaver

    async def open(self) -> None: ...

    async def close(self) -> None: ...

    async def ping(self) -> None: ...


class MemoryPersistence(Persistence):
    """In-process store and checkpointer for tests; requires no database."""

    def __init__(self):
        self.store = InMemoryConversationStore()
        self.checkpointer = InMemorySaver()


class PostgresPersistence(Persistence):
    def __init__(self, database_url: str, pool_size: int):
        # Small, bounded pools for Neon's free plan; pre-ping covers compute auto-suspend.
        self.engine = create_async_engine(
            sqlalchemy_url(database_url),
            pool_size=pool_size,
            max_overflow=0,
            pool_pre_ping=True,
            pool_recycle=300,
        )
        sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self._sql_store = SqlConversationStore(sessions)
        self.store = self._sql_store
        self.pool = AsyncConnectionPool(
            libpq_url(database_url),
            min_size=1,
            max_size=pool_size,
            open=False,
            kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
        )

    async def open(self) -> None:
        await self.pool.open()
        # The saver binds to the running event loop, so it is created here, not in __init__.
        self.checkpointer = AsyncPostgresSaver(conn=self.pool)

    async def close(self) -> None:
        try:
            await self.pool.close()
        finally:
            await self.engine.dispose()

    async def ping(self) -> None:
        async with asyncio.timeout(2):
            await self._sql_store.ping()
