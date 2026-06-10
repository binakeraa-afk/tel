"""
Fabrique de file d'attente (pattern Strategy).

Sélectionne le backend selon la configuration (db | redis). Le backend DB est le
défaut résilient ; Redis est un accélérateur optionnel.
"""
from __future__ import annotations

from app.config import Settings
from app.core.interfaces import IQueueBackend
from app.db.repositories import VideoRepository
from app.queue.db_backend import DBQueueBackend
from app.utils.logging_config import get_logger

log = get_logger("queue_factory")


def build_queue_backend(settings: Settings, video_repo: VideoRepository) -> IQueueBackend:
    if settings.queue_backend == "redis" and settings.redis_url:
        try:
            from app.queue.redis_backend import RedisQueueBackend
            log.info("queue.backend", kind="redis")
            return RedisQueueBackend(video_repo, settings.redis_url)
        except Exception as exc:  # noqa: BLE001 — repli automatique sur DB
            log.warning("queue.redis_unavailable_fallback_db", error=repr(exc))
    log.info("queue.backend", kind="db")
    return DBQueueBackend(video_repo)


__all__ = ["build_queue_backend", "DBQueueBackend"]
