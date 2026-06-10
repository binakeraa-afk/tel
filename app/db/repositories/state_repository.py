"""
StateRepository : état global du planificateur (ligne unique).

Gère aussi la séquence FIFO atomique (`next_queue_seq`) utilisée pour ordonner
les vidéos par ordre d'arrivée de façon fiable même en concurrence.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select, update

from app.db.repositories.base import BaseRepository
from app.models import SystemState
from app.utils.logging_config import get_logger

log = get_logger("state_repo")


class StateRepository(BaseRepository):

    async def _ensure_row(self, s) -> SystemState:
        res = await s.execute(select(SystemState).where(SystemState.id == 1))
        state = res.scalar_one_or_none()
        if state is None:
            state = SystemState(id=1)
            s.add(state)
            await s.flush()
        return state

    async def get(self) -> SystemState:
        async with self.db.session_scope() as s:
            state = await self._ensure_row(s)
            await s.refresh(state)
            s.expunge(state)
            return state

    async def update_fields(self, **fields) -> None:
        async with self.db.session_scope() as s:
            await self._ensure_row(s)
            await s.execute(update(SystemState).where(SystemState.id == 1).values(**fields))

    async def next_queue_seq(self) -> int:
        """Incrémente et renvoie la séquence FIFO (atomique au sein de la transaction)."""
        async with self.db.session_scope() as s:
            state = await self._ensure_row(s)
            state.queue_counter += 1
            state.total_ingested += 1
            return state.queue_counter

    async def set_next_post_at(self, when: datetime) -> None:
        await self.update_fields(next_post_at=when)

    async def mark_published(self, when: datetime) -> None:
        async with self.db.session_scope() as s:
            state = await self._ensure_row(s)
            state.total_published += 1
            state.last_published_at = when

    async def mark_failed(self) -> None:
        async with self.db.session_scope() as s:
            state = await self._ensure_row(s)
            state.total_failed += 1

    async def set_paused(self, paused: bool) -> None:
        await self.update_fields(paused=paused)

    # ── Cookies de session X (mode unofficial) ────────────────────────────────
    async def get_cookies(self) -> str | None:
        async with self.db.session_scope() as s:
            state = await self._ensure_row(s)
            return state.x_cookies_json

    async def set_cookies(self, cookies_json: str | None) -> None:
        await self.update_fields(x_cookies_json=cookies_json)
