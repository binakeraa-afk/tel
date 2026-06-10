"""
VideoRepository : toutes les opérations de persistance des vidéos.

Encapsule la machine à états (les changements de statut passent par
`transition`, qui valide la transition avant d'écrire).
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select, update

from app.core.enums import PUBLISHABLE_STATUSES, TERMINAL_STATUSES, VideoStatus
from app.core.state_machine import StateMachine
from app.db.repositories.base import BaseRepository
from app.models import Video
from app.utils.logging_config import get_logger

log = get_logger("video_repo")


class VideoRepository(BaseRepository):

    # ── Lecture ────────────────────────────────────────────────────────────────
    async def get(self, video_id: int) -> Video | None:
        async with self.db.session_scope() as s:
            res = await s.execute(select(Video).where(Video.id == video_id))
            v = res.scalar_one_or_none()
            if v is not None:
                s.expunge(v)
            return v

    async def exists_by_unique_id(self, file_unique_id: str) -> bool:
        async with self.db.session_scope() as s:
            res = await s.execute(
                select(func.count()).select_from(Video).where(
                    Video.tg_file_unique_id == file_unique_id
                )
            )
            return (res.scalar_one() or 0) > 0

    async def exists_by_sha256(self, digest: str) -> bool:
        async with self.db.session_scope() as s:
            res = await s.execute(
                select(func.count()).select_from(Video).where(Video.sha256 == digest)
            )
            return (res.scalar_one() or 0) > 0

    async def next_publishable(self) -> Video | None:
        """Prochaine vidéo prête à publier, dans l'ordre FIFO (queue_seq)."""
        async with self.db.session_scope() as s:
            res = await s.execute(
                select(Video)
                .where(Video.status.in_(tuple(PUBLISHABLE_STATUSES)))
                .order_by(Video.queue_seq.asc())
                .limit(1)
            )
            v = res.scalar_one_or_none()
            if v is not None:
                s.expunge(v)
            return v

    async def pending_count(self) -> int:
        async with self.db.session_scope() as s:
            res = await s.execute(
                select(func.count()).select_from(Video).where(
                    Video.status.notin_(tuple(TERMINAL_STATUSES))
                )
            )
            return res.scalar_one() or 0

    async def stuck_in_progress(self) -> list[Video]:
        """Vidéos restées en cours (DOWNLOADING/VERIFYING/PUBLISHING) après crash."""
        active = (VideoStatus.DOWNLOADING, VideoStatus.VERIFYING, VideoStatus.PUBLISHING)
        async with self.db.session_scope() as s:
            res = await s.execute(select(Video).where(Video.status.in_(active)))
            items = list(res.scalars().all())
            for it in items:
                s.expunge(it)
            return items

    # ── Écriture ───────────────────────────────────────────────────────────────
    async def create(self, **fields) -> Video:
        async with self.db.session_scope() as s:
            v = Video(**fields)
            s.add(v)
            await s.flush()
            await s.refresh(v)
            s.expunge(v)
            return v

    async def update_fields(self, video_id: int, **fields) -> None:
        if not fields:
            return
        async with self.db.session_scope() as s:
            await s.execute(update(Video).where(Video.id == video_id).values(**fields))

    async def transition(self, video_id: int, target: VideoStatus, **extra) -> bool:
        """Change le statut en validant la transition. Renvoie False si illégale."""
        async with self.db.session_scope() as s:
            res = await s.execute(select(Video).where(Video.id == video_id))
            v = res.scalar_one_or_none()
            if v is None:
                return False
            if not StateMachine.validate(v.status, target):
                return False
            v.status = target
            for k, val in extra.items():
                setattr(v, k, val)
            if target is VideoStatus.PUBLISHED and v.published_at is None:
                v.published_at = datetime.now(timezone.utc)
            return True

    async def increment_attempts(self, video_id: int) -> None:
        async with self.db.session_scope() as s:
            await s.execute(
                update(Video).where(Video.id == video_id).values(attempts=Video.attempts + 1)
            )

    async def requeue_stuck(self) -> int:
        """Au boot : remet les vidéos « coincées » dans un état repartable."""
        items = await self.stuck_in_progress()
        for v in items:
            # PUBLISHING/VERIFYING → on revient à un état sûr en amont.
            target = VideoStatus.PENDING if v.file_path is None else VideoStatus.DOWNLOADED
            await self.update_fields(v.id, status=target)
        if items:
            log.info("video.requeued_stuck", count=len(items))
        return len(items)
