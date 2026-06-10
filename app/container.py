"""
Conteneur d'injection de dépendances (composition root).

Centralise la CONSTRUCTION et le CÂBLAGE de tous les composants. Le reste du code
ne fait jamais de `new` d'un service : tout est assemblé ici, ce qui rend le
système testable (on peut injecter des mocks) et modulaire.
"""
from __future__ import annotations

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from app.config import get_settings
from app.db import Database
from app.db.repositories import LogRepository, StateRepository, VideoRepository
from app.queue import build_queue_backend
from app.schedulers import PostingScheduler
from app.services.compression_service import CompressionService
from app.services.download_service import DownloadService
from app.services.ingest_service import IngestService
from app.services.monitoring_service import MonitoringService, Notifier
from app.services.publish_service import PublishService
from app.services.verification_service import VerificationService
from app.services.x_client import XClient
from app.utils.logging_config import get_logger

log = get_logger("container")


class Container:
    """Assemble et expose tous les composants applicatifs."""

    def __init__(self) -> None:
        self.settings = get_settings()

        # ── Infrastructure ────────────────────────────────────────────────────
        self.db = Database()
        self.bot = self._build_bot()

        # ── Repositories ──────────────────────────────────────────────────────
        self.video_repo = VideoRepository(self.db)
        self.state_repo = StateRepository(self.db)
        self.log_repo = LogRepository(self.db)

        # ── Services techniques ──────────────────────────────────────────────
        self.notifier = Notifier(self.bot)
        self.downloader = DownloadService(self.bot)
        self.verifier = VerificationService()
        self.compressor = CompressionService()
        self.publisher = self._build_publisher()
        self.queue_backend = build_queue_backend(self.settings, self.video_repo)

        # ── Services métier ──────────────────────────────────────────────────
        self.ingest = IngestService(
            video_repo=self.video_repo,
            state_repo=self.state_repo,
            downloader=self.downloader,
            verifier=self.verifier,
        )
        self.publish = PublishService(
            video_repo=self.video_repo,
            state_repo=self.state_repo,
            log_repo=self.log_repo,
            publisher=self.publisher,
            downloader=self.downloader,
            verifier=self.verifier,
            compressor=self.compressor,
        )
        self.monitoring = MonitoringService(
            video_repo=self.video_repo, state_repo=self.state_repo
        )
        self.scheduler = PostingScheduler(
            publish_service=self.publish,
            state_repo=self.state_repo,
            notifier=self.notifier,
        )

    # ── Sélection du publisher X (officiel Tweepy ou non-officiel twikit) ─────
    def _build_publisher(self):
        if self.settings.x_mode == "official":
            log.info("publisher.mode", mode="official")
            return XClient()
        log.info("publisher.mode", mode="unofficial")
        from app.services.twikit_client import TwikitPublisher
        return TwikitPublisher(self.state_repo)

    # ── Construction du Bot (avec serveur Bot API local optionnel) ────────────
    def _build_bot(self) -> Bot:
        session = None
        if self.settings.telegram_api_url:
            # Serveur Bot API local => lève la limite de téléchargement à 2 Go.
            from aiogram.client.session.aiohttp import AiohttpSession
            from aiogram.client.telegram import TelegramAPIServer

            server = TelegramAPIServer.from_base(self.settings.telegram_api_url)
            session = AiohttpSession(api=server)
            log.info("bot.local_api_server", url=self.settings.telegram_api_url)

        return Bot(
            token=self.settings.bot_token,
            session=session,
            default=DefaultBotProperties(
                parse_mode=ParseMode.HTML, link_preview_is_disabled=True
            ),
        )

    # ── Cycle de vie ──────────────────────────────────────────────────────────
    async def start(self) -> None:
        """Démarre l'infrastructure et reprend l'état (résilience)."""
        await self.db.init()

        # Vérification non bloquante de l'accès X (log seulement).
        if self.settings.x_ready:
            try:
                await self.publisher.healthcheck()
            except Exception as exc:  # noqa: BLE001
                log.error("container.x_healthcheck_failed", error=repr(exc))
        else:
            log.warning("container.x_not_configured", mode=self.settings.x_mode)

        await self.ingest.start()
        await self.ingest.requeue_unfinished()
        await self.scheduler.start()
        log.info("container.started")

    async def stop(self) -> None:
        await self.scheduler.stop()
        await self.ingest.stop()
        await self.db.dispose()
        try:
            await self.bot.session.close()
        except Exception:  # noqa: BLE001
            pass
        log.info("container.stopped")
