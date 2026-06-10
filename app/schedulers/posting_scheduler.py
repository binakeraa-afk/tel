"""
PostingScheduler : planifie « une vidéo toutes les 3 heures ».

Conception « tick + créneau persisté » (plutôt qu'un simple cron toutes les 3 h) :
  - Un job APScheduler s'exécute fréquemment (SCHEDULER_TICK_SECONDS, 60 s).
  - À chaque tick, on regarde `next_post_at` (persisté en base). S'il est échu et
    qu'une vidéo est prête, on publie UNE vidéo et on programme le prochain créneau.
  - Avantages : résilient au redémarrage (le créneau survit en base), précis,
    et auto-rattrapant (si le bot était down, il publie dès qu'il revient).

Garde-fous :
  - Verrou asyncio : deux ticks ne se chevauchent jamais.
  - Fenêtre horaire active optionnelle (ACTIVE_HOUR_START/END en UTC).
  - Pause globale honorée (commande admin /pause).
"""
from __future__ import annotations

import asyncio
from datetime import timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import get_settings
from app.db.repositories import StateRepository
from app.services.monitoring_service import Notifier
from app.services.publish_service import OutcomeStatus, PublishService
from app.utils.logging_config import get_logger
from app.utils.timeutils import as_utc, now_utc

log = get_logger("scheduler")


class PostingScheduler:
    def __init__(
        self,
        *,
        publish_service: PublishService,
        state_repo: StateRepository,
        notifier: Notifier,
    ) -> None:
        self.publish_service = publish_service
        self.state_repo = state_repo
        self.notifier = notifier
        self.settings = get_settings()
        self._scheduler = AsyncIOScheduler(timezone="UTC")
        self._lock = asyncio.Lock()

    # ── Cycle de vie ───────────────────────────────────────────────────────────
    async def start(self) -> None:
        # S'assure qu'un premier créneau existe (sinon, publie dès qu'une vidéo arrive).
        state = await self.state_repo.get()
        if state.next_post_at is None:
            await self.state_repo.set_next_post_at(now_utc())

        self._scheduler.add_job(
            self._tick,
            trigger="interval",
            seconds=self.settings.scheduler_tick_seconds,
            id="posting_tick",
            max_instances=1,        # APScheduler empêche déjà le chevauchement
            coalesce=True,
            misfire_grace_time=3600,
        )
        self._scheduler.start()
        log.info("scheduler.started", tick=self.settings.scheduler_tick_seconds,
                 interval=self.settings.post_interval_seconds)

    async def stop(self) -> None:
        try:
            self._scheduler.shutdown(wait=False)
        except Exception as exc:  # noqa: BLE001
            log.warning("scheduler.shutdown_failed", error=repr(exc))

    # ── Boucle de décision ─────────────────────────────────────────────────────
    async def _tick(self) -> None:
        if self._lock.locked():
            return
        async with self._lock:
            try:
                await self._evaluate()
            except Exception as exc:  # noqa: BLE001 — un tick ne crash jamais le bot
                log.error("scheduler.tick_error", error=repr(exc), exc_info=True)

    async def _evaluate(self) -> None:
        state = await self.state_repo.get()
        if state.paused:
            return
        if not self._within_active_hours():
            return

        now = now_utc()
        next_at = as_utc(state.next_post_at) or now
        if now < next_at:
            return  # pas encore l'heure

        # Créneau dû : on tente de publier une vidéo.
        outcome = await self.publish_service.publish_next()

        if outcome.status is OutcomeStatus.PUBLISHED:
            await self.state_repo.set_next_post_at(
                now + timedelta(seconds=self.settings.post_interval_seconds)
            )
            await self.notifier.notify(
                f"✅ Vidéo publiée sur X.\n🔗 tweet id: <code>{outcome.tweet_id}</code>"
            )
            log.info("scheduler.published", tweet_id=outcome.tweet_id)

        elif outcome.status is OutcomeStatus.EMPTY:
            # Rien à publier : on ne déplace pas le créneau (post immédiat dès qu'une
            # vidéo prête arrive et que le créneau est échu).
            return

        else:  # RETRY ou SKIPPED : court délai pour ne pas marteler X.
            retry_delay = min(self.settings.post_interval_seconds, 300)
            await self.state_repo.set_next_post_at(now + timedelta(seconds=retry_delay))
            log.warning("scheduler.deferred", status=outcome.status.value, retry_in=retry_delay)

    # ── Helpers ────────────────────────────────────────────────────────────────
    def _within_active_hours(self) -> bool:
        start = self.settings.active_hour_start
        end = self.settings.active_hour_end
        if start == 0 and end == 24:
            return True
        hour = now_utc().hour
        if start <= end:
            return start <= hour < end
        # Fenêtre qui passe minuit (ex: 22 → 6).
        return hour >= start or hour < end

    # ── Action manuelle (commande admin /next) ─────────────────────────────────
    async def force_now(self) -> str:
        """Force une publication immédiate (hors planning). Renvoie un message."""
        async with self._lock:
            outcome = await self.publish_service.publish_next()
            if outcome.status is OutcomeStatus.PUBLISHED:
                await self.state_repo.set_next_post_at(
                    now_utc() + timedelta(seconds=self.settings.post_interval_seconds)
                )
                return f"✅ Publiée (tweet {outcome.tweet_id})."
            if outcome.status is OutcomeStatus.EMPTY:
                return "ℹ️ Aucune vidéo prête à publier."
            return f"⚠️ Échec ({outcome.status.value}), nouvel essai planifié."
