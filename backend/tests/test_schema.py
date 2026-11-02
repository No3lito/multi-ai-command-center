"""The database schema produced by migrations must match the SQLAlchemy models exactly."""

from __future__ import annotations

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from command_center.db.models import Base


async def test_migrations_match_models(database_url: str) -> None:
    engine = create_async_engine(database_url.replace("postgresql://", "postgresql+asyncpg://", 1))

    def diff(conn: Connection) -> list[object]:
        return compare_metadata(MigrationContext.configure(conn), Base.metadata)  # type: ignore[no-any-return]

    async with engine.connect() as conn:
        changes = await conn.run_sync(diff)
    await engine.dispose()
    assert changes == []
