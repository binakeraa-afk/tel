"""
Moteur de base de données asynchrone + fabrique de sessions.

Compatible PostgreSQL (Railway) et SQLite (dev). Expose un context manager
transactionnel `session_scope()` et un filet `create_all` au boot (au cas où
Alembic n'aurait pas tourné).
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings
from app.models.base import Base
from app.utils.logging_config import get_logger

log = get_logger("db")


class Database:
    """Encapsule le moteur et la fabrique de sessions (injectable)."""

    def __init__(self) -> None:
        self._engine: AsyncEngine | None = None
        self._sessionmaker: async_sessionmaker[AsyncSession] | None = None

    async def init(self) -> None:
        if self._engine is not None:
            return
        s = get_settings()
        connect_args: dict = {}
        kwargs: dict = {"echo": False, "pool_pre_ping": True}
        if s.database_url.startswith("sqlite"):
            connect_args = {"timeout": 30}
            kwargs.pop("pool_pre_ping")

        self._engine = create_async_engine(s.database_url, connect_args=connect_args, **kwargs)
        self._sessionmaker = async_sessionmaker(
            self._engine, expire_on_commit=False, class_=AsyncSession
        )
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        log.info("db.initialized", backend="postgres" if s.is_postgres else "sqlite")

    @property
    def sessionmaker(self) -> async_sessionmaker[AsyncSession]:
        if self._sessionmaker is None:
            raise RuntimeError("Database.init() doit être appelé d'abord")
        return self._sessionmaker

    @asynccontextmanager
    async def session_scope(self) -> AsyncIterator[AsyncSession]:
        session = self.sessionmaker()
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def dispose(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None
            log.info("db.disposed")
