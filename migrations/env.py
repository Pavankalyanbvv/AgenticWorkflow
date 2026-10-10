import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.config import Settings
from app.db.models import Base
from app.db.persistence import sqlalchemy_url

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Tables owned by LangGraph's AsyncPostgresSaver; never autogenerate changes for them.
LANGGRAPH_TABLES = {"checkpoints", "checkpoint_blobs", "checkpoint_writes", "checkpoint_migrations"}


def include_object(object, name, type_, reflected, compare_to) -> bool:
    return not (type_ == "table" and name in LANGGRAPH_TABLES)


def database_url() -> str:
    settings = Settings()
    if not settings.database_url or not settings.database_url.get_secret_value().strip():
        raise RuntimeError("Set DATABASE_URL in .env before running migrations.")
    return sqlalchemy_url(settings.database_url.get_secret_value().strip())


def run_migrations_offline() -> None:
    context.configure(
        url=database_url(),
        target_metadata=target_metadata,
        include_object=include_object,
        literal_binds=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(
        connection=connection, target_metadata=target_metadata, include_object=include_object
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(database_url(), poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(do_run_migrations)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
