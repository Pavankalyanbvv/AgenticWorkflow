"""Apply schema changes: Alembic migrations, then LangGraph checkpoint tables.

Run explicitly (the app never changes the schema at startup):
    uv run python -m app.db.migrate
"""

import asyncio
from pathlib import Path

from alembic import command
from alembic.config import Config
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.config import Settings
from app.db.persistence import libpq_url

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


async def setup_checkpointer(database_url: str) -> None:
    async with AsyncPostgresSaver.from_conn_string(libpq_url(database_url)) as saver:
        await saver.setup()


def main() -> None:
    settings = Settings()
    if not settings.database_url or not settings.database_url.get_secret_value().strip():
        raise SystemExit("Set DATABASE_URL in .env before running migrations.")
    command.upgrade(Config(str(ALEMBIC_INI)), "head")
    asyncio.run(setup_checkpointer(settings.database_url.get_secret_value().strip()))
    print("Migrations applied and checkpoint tables ready.")


if __name__ == "__main__":
    main()
