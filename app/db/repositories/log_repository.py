"""LogRepository : journal d'audit des publications."""
from __future__ import annotations

from app.db.repositories.base import BaseRepository
from app.models import PostLog


class LogRepository(BaseRepository):
    async def add(
        self, *, video_id: int | None, success: bool, attempt: int,
        tweet_id: str | None = None, error: str | None = None,
    ) -> None:
        async with self.db.session_scope() as s:
            s.add(PostLog(
                video_id=video_id, success=success, attempt=attempt,
                tweet_id=tweet_id, error=(error or "")[:1000] or None,
            ))
