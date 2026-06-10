"""
IngestService : pipeline d'entrée (canal Telegram → file « prête à publier »).

Flux par vidéo :
  PENDING → (download) → DOWNLOADED → (verify) → READY
                                              ↘ SKIPPED_DUPLICATE (doublon sha256)

Conception :
  - Le handler Telegram appelle `register()` : dédup rapide + création de la ligne
    + mise en file interne. Il rend la main immédiatement (pas de blocage).
  - Un petit pool de workers télécharge/vérifie en arrière-plan, avec retries.
  - Au boot, `requeue_unfinished()` reprend les vidéos non terminées (résilience).
"""
from __future__ import annotations

import asyncio

from aiogram.types import Message

from app.config import get_settings
from app.core.enums import MediaSourceType, VideoStatus
from app.core.exceptions import FatalError, RetryableError
from app.core.interfaces import IDownloader, IVerifier
from app.db.repositories import StateRepository, VideoRepository
from app.utils.files import safe_unlink
from app.utils.logging_config import get_logger
from app.utils.retry import RetryExhausted, retry_call

log = get_logger("ingest")


class IngestService:
    def __init__(
        self,
        *,
        video_repo: VideoRepository,
        state_repo: StateRepository,
        downloader: IDownloader,
        verifier: IVerifier,
        concurrency: int = 2,
    ) -> None:
        self.video_repo = video_repo
        self.state_repo = state_repo
        self.downloader = downloader
        self.verifier = verifier
        self.settings = get_settings()
        self._queue: asyncio.Queue[int] = asyncio.Queue()
        self._workers: list[asyncio.Task] = []
        self._concurrency = concurrency
        self._inflight: set[int] = set()
        self._lock = asyncio.Lock()

    # ── Cycle de vie ───────────────────────────────────────────────────────────
    async def start(self) -> None:
        for i in range(self._concurrency):
            self._workers.append(asyncio.create_task(self._worker(i), name=f"ingest-{i}"))
        log.info("ingest.started", workers=self._concurrency)

    async def stop(self) -> None:
        for t in self._workers:
            t.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()

    async def _enqueue(self, video_id: int) -> None:
        async with self._lock:
            if video_id in self._inflight:
                return
            self._inflight.add(video_id)
        await self._queue.put(video_id)

    async def requeue_unfinished(self) -> int:
        """Reprend au boot les vidéos non encore READY/terminales."""
        await self.video_repo.requeue_stuck()
        count = 0
        # Les vidéos encore « en cours » (rare après requeue_stuck) repassent en file.
        for v in await self.video_repo.stuck_in_progress():
            await self._enqueue(v.id)
            count += 1
        # PENDING (y compris celles réinitialisées par requeue_stuck) repassent en file.
        pending = await self._collect_unready()
        for vid in pending:
            await self._enqueue(vid)
            count += 1
        if count:
            log.info("ingest.requeued", count=count)
        return count

    async def _collect_unready(self) -> list[int]:
        """Ids des vidéos PENDING (à (re)traiter par le pipeline d'ingestion)."""
        from sqlalchemy import select
        from app.models import Video
        async with self.video_repo.db.session_scope() as s:
            res = await s.execute(
                select(Video.id).where(Video.status == VideoStatus.PENDING)
            )
            return [row[0] for row in res.all()]

    # ── Enregistrement d'une nouvelle vidéo ───────────────────────────────────
    async def register(self, message: Message) -> bool:
        """Détecte/enregistre une vidéo d'un message de canal. Renvoie True si prise
        en compte (nouvelle), False sinon (ignorée/doublon). Ne lève jamais."""
        try:
            media = self._extract_media(message)
            if media is None:
                return False
            file_id, file_unique_id, size, _kind = media

            # Dédup primaire (file_unique_id stable).
            if await self.video_repo.exists_by_unique_id(file_unique_id):
                log.info("ingest.duplicate_unique_id", uid=file_unique_id)
                return False

            seq = await self.state_repo.next_queue_seq()
            channel = message.chat.title or (message.chat.username or str(message.chat.id))
            video = await self.video_repo.create(
                tg_file_unique_id=file_unique_id,
                tg_file_id=file_id,
                tg_chat_id=message.chat.id,
                tg_message_id=message.message_id,
                source_channel=str(channel)[:255],
                original_caption=(message.caption or None),
                status=VideoStatus.PENDING,
                queue_seq=seq,
                file_size=size,
            )
            await self._enqueue(video.id)
            log.info("ingest.registered", video_id=video.id, seq=seq, size=size)
            return True
        except Exception as exc:  # noqa: BLE001 — jamais d'erreur visible
            log.error("ingest.register_failed", error=repr(exc))
            return False

    @staticmethod
    def _extract_media(message: Message) -> tuple[str, str, int | None, MediaSourceType] | None:
        """Extrait (file_id, file_unique_id, taille, type) d'un message vidéo."""
        if message.video is not None:
            v = message.video
            return v.file_id, v.file_unique_id, v.file_size, MediaSourceType.VIDEO
        if message.animation is not None:
            a = message.animation
            return a.file_id, a.file_unique_id, a.file_size, MediaSourceType.ANIMATION
        doc = message.document
        if doc is not None and (doc.mime_type or "").startswith("video/"):
            return doc.file_id, doc.file_unique_id, doc.file_size, MediaSourceType.DOCUMENT_VIDEO
        return None

    # ── Worker d'ingestion ─────────────────────────────────────────────────────
    async def _worker(self, index: int) -> None:
        while True:
            video_id = await self._queue.get()
            try:
                await self._process(video_id)
            except Exception as exc:  # noqa: BLE001
                log.error("ingest.worker_error", worker=index, video_id=video_id, error=repr(exc))
            finally:
                async with self._lock:
                    self._inflight.discard(video_id)
                self._queue.task_done()

    async def _process(self, video_id: int) -> None:
        video = await self.video_repo.get(video_id)
        if video is None or video.status in (
            VideoStatus.READY, VideoStatus.PUBLISHED, VideoStatus.PUBLISHING,
        ):
            return

        import structlog
        structlog.contextvars.bind_contextvars(video_id=video_id)
        dest = self.settings.work_dir / f"video_{video_id}.mp4"

        try:
            # ── Téléchargement (avec retries) ─────────────────────────────────
            await self.video_repo.transition(video_id, VideoStatus.DOWNLOADING)
            await self.video_repo.increment_attempts(video_id)

            async def _dl():
                return await self.downloader.download(
                    file_id=video.tg_file_id, dest=dest, expected_size=video.file_size
                )

            try:
                await retry_call(
                    _dl, op_name="download",
                    retry_on=(RetryableError,), give_up_on=(FatalError,),
                )
            except (RetryExhausted, FatalError) as exc:
                last = getattr(exc, "last_exc", exc)
                await self.video_repo.transition(
                    video_id, VideoStatus.FAILED, last_error=repr(last)[:500]
                )
                await safe_unlink(dest)
                return

            await self.video_repo.transition(
                video_id, VideoStatus.DOWNLOADED, file_path=str(dest)
            )

            # ── Vérification d'intégrité ──────────────────────────────────────
            await self.video_repo.transition(video_id, VideoStatus.VERIFYING)
            integrity = await self.verifier.verify(dest, require_video=True)
            if integrity is None:
                await self.video_repo.transition(
                    video_id, VideoStatus.FAILED, last_error="intégrité invalide"
                )
                await safe_unlink(dest)
                return

            # ── Dédup secondaire par contenu (sha256) ─────────────────────────
            if await self.video_repo.exists_by_sha256(integrity.sha256):
                await self.video_repo.transition(video_id, VideoStatus.SKIPPED_DUPLICATE)
                await safe_unlink(dest)
                log.info("ingest.duplicate_sha", sha=integrity.sha256[:12])
                return

            probe = integrity.probe
            await self.video_repo.transition(
                video_id, VideoStatus.READY,
                file_path=str(dest), file_size=integrity.size, sha256=integrity.sha256,
                duration=(probe.duration if probe else None),
                width=(probe.width if probe else None),
                height=(probe.height if probe else None),
            )
            log.info("ingest.ready", video_id=video_id)
        finally:
            structlog.contextvars.clear_contextvars()
