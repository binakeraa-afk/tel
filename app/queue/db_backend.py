"""
DBQueueBackend : la file d'attente EST la base de données.

C'est le backend par défaut et le plus résilient : il n'existe pas de file
« en plus » à resynchroniser après un crash — l'état des vidéos en base est
l'unique source de vérité, donc la reprise est exacte par construction.
"""
from __future__ import annotations

from app.core.interfaces import IQueueBackend
from app.db.repositories import VideoRepository


class DBQueueBackend(IQueueBackend):
    def __init__(self, video_repo: VideoRepository) -> None:
        self.video_repo = video_repo

    async def enqueue(self, video_id: int) -> None:
        # No-op : la ligne en base, avec son `queue_seq`, fait foi.
        return None

    async def next_ready(self) -> int | None:
        v = await self.video_repo.next_publishable()
        return v.id if v else None

    async def size(self) -> int:
        return await self.video_repo.pending_count()
