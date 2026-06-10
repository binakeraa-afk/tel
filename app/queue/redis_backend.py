"""
RedisQueueBackend : file d'attente optionnelle basée sur Redis.

⚠️ Important : même avec Redis, la BASE DE DONNÉES reste la source de vérité pour
la reprise après crash. Redis sert ici d'index FIFO rapide / de métrique. La
sélection « prochaine vidéo » délègue à la base pour rester strictement correcte
(l'ordre `queue_seq` y est garanti). Cela évite tout risque de désynchronisation.

Activé via QUEUE_BACKEND=redis + REDIS_URL.
"""
from __future__ import annotations

from app.core.interfaces import IQueueBackend
from app.db.repositories import VideoRepository
from app.utils.logging_config import get_logger

log = get_logger("redis_queue")

_QUEUE_KEY = "poster:queue:ready"


class RedisQueueBackend(IQueueBackend):
    def __init__(self, video_repo: VideoRepository, redis_url: str) -> None:
        self.video_repo = video_repo
        self.redis_url = redis_url
        self._client = None  # connexion paresseuse

    async def _get_client(self):
        if self._client is None:
            import redis.asyncio as aioredis  # import tardif (dépendance optionnelle)
            self._client = aioredis.from_url(self.redis_url, decode_responses=True)
        return self._client

    async def enqueue(self, video_id: int) -> None:
        try:
            client = await self._get_client()
            await client.rpush(_QUEUE_KEY, video_id)
        except Exception as exc:  # noqa: BLE001 — Redis ne doit jamais bloquer
            log.warning("redis.enqueue_failed", error=repr(exc))

    async def next_ready(self) -> int | None:
        # Source de vérité = base (ordre garanti, reprise exacte).
        v = await self.video_repo.next_publishable()
        return v.id if v else None

    async def size(self) -> int:
        try:
            client = await self._get_client()
            n = await client.llen(_QUEUE_KEY)
            if n:
                return int(n)
        except Exception as exc:  # noqa: BLE001
            log.warning("redis.size_failed", error=repr(exc))
        # Repli base.
        return await self.video_repo.pending_count()
