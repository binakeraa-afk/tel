"""
PublishService : publie UNE vidéo sur X, de façon quasi-infaillible.

Appelé par le planificateur quand un créneau est dû. Pipeline :
  1. Sélection FIFO de la prochaine vidéo publiable.
  2. Re-vérification d'intégrité (et re-téléchargement de secours si le fichier a
     disparu du disque).
  3. Compression intelligente si la vidéo dépasse la limite X.
  4. Construction de la légende (template + hashtags, tronquée à 280).
  5. Publication via XClient avec retry (Retryable → réessai, Fatal → abandon).
  6. Persistance du résultat + nettoyage des fichiers.

Renvoie un PublishOutcome que le planificateur utilise pour décider du prochain
créneau (succès → +interval ; échec réessayable → court délai ; rien → inchangé).
"""
from __future__ import annotations

import enum
from dataclasses import dataclass
from pathlib import Path

from app.config import get_settings
from app.core.enums import VideoStatus
from app.core.exceptions import FatalError, RetryableError
from app.core.interfaces import IDownloader, IPublisher, IVerifier
from app.db.repositories import LogRepository, StateRepository, VideoRepository
from app.models import Video
from app.services.compression_service import CompressionService
from app.utils.files import safe_unlink
from app.utils.logging_config import get_logger
from app.utils.retry import RetryExhausted, retry_call

log = get_logger("publish")


class OutcomeStatus(str, enum.Enum):
    PUBLISHED = "published"
    EMPTY = "empty"            # rien à publier
    RETRY = "retry"            # échec réessayable, à retenter bientôt
    SKIPPED = "skipped"        # non publiable (config/pause)


@dataclass
class PublishOutcome:
    status: OutcomeStatus
    video_id: int | None = None
    tweet_id: str | None = None


class PublishService:
    def __init__(
        self,
        *,
        video_repo: VideoRepository,
        state_repo: StateRepository,
        log_repo: LogRepository,
        publisher: IPublisher,
        downloader: IDownloader,
        verifier: IVerifier,
        compressor: CompressionService,
    ) -> None:
        self.video_repo = video_repo
        self.state_repo = state_repo
        self.log_repo = log_repo
        self.publisher = publisher
        self.downloader = downloader
        self.verifier = verifier
        self.compressor = compressor
        self.settings = get_settings()

    async def publish_next(self) -> PublishOutcome:
        """Publie la prochaine vidéo prête. Ne lève jamais."""
        video = await self.video_repo.next_publishable()
        if video is None:
            return PublishOutcome(OutcomeStatus.EMPTY)

        import structlog
        structlog.contextvars.bind_contextvars(video_id=video.id)
        try:
            return await self._publish_one(video)
        except Exception as exc:  # noqa: BLE001 — filet ultime
            log.error("publish.unexpected", error=repr(exc), exc_info=True)
            await self._register_failure(video, repr(exc))
            return PublishOutcome(OutcomeStatus.RETRY, video_id=video.id)
        finally:
            structlog.contextvars.clear_contextvars()

    # ── Pipeline d'une publication ─────────────────────────────────────────────
    async def _publish_one(self, video: Video) -> PublishOutcome:
        # Verrou d'état : on passe en PUBLISHING (empêche le double-traitement).
        if not await self.video_repo.transition(video.id, VideoStatus.PUBLISHING):
            return PublishOutcome(OutcomeStatus.SKIPPED, video_id=video.id)
        await self.video_repo.increment_attempts(video.id)

        # 1) Garantir un fichier valide (re-téléchargement de secours si besoin).
        path = await self._ensure_file(video)
        if path is None:
            await self._fail_terminal(video, "fichier indisponible/illisible")
            return PublishOutcome(OutcomeStatus.RETRY, video_id=video.id)

        # 2) Compression si trop lourd pour X.
        upload_path, compressed = await self._maybe_compress(path)

        # 3) Légende.
        caption = self._build_caption(video)

        # 4) Publication avec retry (Retryable → réessai ; Fatal → abandon).
        async def _do_publish() -> str:
            return await self.publisher.publish_video(path=upload_path, caption=caption)

        try:
            tweet_id = await retry_call(
                _do_publish, op_name="x_publish",
                retry_on=(RetryableError,), give_up_on=(FatalError,),
            )
        except FatalError as exc:
            await self._fail_terminal(video, f"fatal: {exc}")
            if compressed:
                await safe_unlink(upload_path)
            return PublishOutcome(OutcomeStatus.SKIPPED, video_id=video.id)
        except RetryExhausted as exc:
            await self._register_failure(video, f"épuisé: {getattr(exc, 'last_exc', exc)!r}")
            if compressed:
                await safe_unlink(upload_path)
            # On laisse la vidéo en READY pour un nouvel essai ultérieur si possible.
            await self._back_to_ready_or_fail(video)
            return PublishOutcome(OutcomeStatus.RETRY, video_id=video.id)

        # 5) Succès.
        await self.video_repo.transition(
            video.id, VideoStatus.PUBLISHED,
            x_tweet_id=tweet_id, published_caption=caption,
        )
        await self.state_repo.mark_published(_now())
        await self.log_repo.add(
            video_id=video.id, success=True, attempt=video.attempts + 1, tweet_id=tweet_id
        )
        # Nettoyage des fichiers.
        await safe_unlink(path)
        if compressed:
            await safe_unlink(upload_path)
        log.info("publish.success", video_id=video.id, tweet_id=tweet_id)
        return PublishOutcome(OutcomeStatus.PUBLISHED, video_id=video.id, tweet_id=tweet_id)

    # ── Helpers ────────────────────────────────────────────────────────────────
    async def _ensure_file(self, video: Video) -> Path | None:
        """Garantit un fichier intègre ; re-télécharge depuis Telegram si absent."""
        if video.file_path:
            p = Path(video.file_path)
            integrity = await self.verifier.verify(p, require_video=True)
            if integrity is not None:
                return p

        # Re-téléchargement de secours.
        dest = self.settings.work_dir / f"video_{video.id}.mp4"
        try:
            async def _dl():
                return await self.downloader.download(
                    file_id=video.tg_file_id, dest=dest, expected_size=video.file_size
                )
            await retry_call(_dl, op_name="redownload",
                             retry_on=(RetryableError,), give_up_on=(FatalError,))
        except Exception as exc:  # noqa: BLE001
            log.warning("publish.redownload_failed", error=repr(exc))
            return None

        integrity = await self.verifier.verify(dest, require_video=True)
        if integrity is None:
            return None
        await self.video_repo.update_fields(
            video.id, file_path=str(dest), file_size=integrity.size, sha256=integrity.sha256
        )
        return dest

    async def _maybe_compress(self, path: Path) -> tuple[Path, bool]:
        """Renvoie (chemin_à_uploader, a_été_compressé)."""
        try:
            size = path.stat().st_size
        except OSError:
            return path, False
        if size <= self.settings.x_max_video_bytes:
            return path, False
        log.info("publish.compress_needed", size=size)
        out = await self.compressor.compress_to_fit(path, self.settings.x_max_video_bytes)
        if out is None:
            # Impossible de compresser : on tente quand même l'original.
            return path, False
        return out, True

    def _build_caption(self, video: Video) -> str:
        s = self.settings
        base = (video.original_caption or "").strip()
        # Un template invalide ne doit jamais faire échouer une publication :
        # on retombe alors sur la légende d'origine.
        try:
            text = s.caption_template.format(
                caption=base,
                channel=video.source_channel or "",
                index=video.queue_seq,
                date=_now().strftime("%Y-%m-%d"),
            ).strip()
        except Exception:  # noqa: BLE001
            text = base
        text = (text + s.hashtags_suffix).strip()
        # Limite X : 280 caractères.
        if len(text) > 280:
            text = text[:277].rstrip() + "…"
        return text or "."

    async def _back_to_ready_or_fail(self, video: Video) -> None:
        """Décide si on réessaie plus tard (READY) ou si on abandonne (FAILED)."""
        fresh = await self.video_repo.get(video.id)
        attempts = fresh.attempts if fresh else video.attempts
        if attempts >= self.settings.max_retries:
            await self._fail_terminal(video, "trop de tentatives")
        else:
            await self.video_repo.transition(video.id, VideoStatus.READY)

    async def _fail_terminal(self, video: Video, reason: str) -> None:
        await self.video_repo.transition(video.id, VideoStatus.FAILED, last_error=reason[:500])
        await self.state_repo.mark_failed()
        await self.log_repo.add(
            video_id=video.id, success=False, attempt=video.attempts + 1, error=reason
        )
        log.error("publish.failed_terminal", video_id=video.id, reason=reason)

    async def _register_failure(self, video: Video, reason: str) -> None:
        await self.log_repo.add(
            video_id=video.id, success=False, attempt=video.attempts + 1, error=reason
        )
        await self._back_to_ready_or_fail(video)


def _now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc)
