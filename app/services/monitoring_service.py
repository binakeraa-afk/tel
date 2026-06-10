"""
MonitoringService : observabilité interne.

- Notifier : envoie des messages au chat admin (best-effort, jamais bloquant).
- build_status_text : compose un rapport lisible (file, publiés, échecs, prochain
  créneau, pause) consommé par la commande /status et les notifications.
"""
from __future__ import annotations

from aiogram import Bot

from app.config import get_settings
from app.db.repositories import StateRepository, VideoRepository
from app.utils.decorators import silent
from app.utils.logging_config import get_logger
from app.utils.timeutils import as_utc, now_utc

log = get_logger("monitoring")


class Notifier:
    """Canal de notification vers le chat admin (implémente INotifier)."""

    def __init__(self, bot: Bot) -> None:
        self.bot = bot
        self.settings = get_settings()

    @silent(op="notify")
    async def notify(self, text: str) -> None:
        chat_id = self.settings.admin_chat_id
        if chat_id is None:
            return
        await self.bot.send_message(chat_id, text)


class MonitoringService:
    def __init__(self, *, video_repo: VideoRepository, state_repo: StateRepository) -> None:
        self.video_repo = video_repo
        self.state_repo = state_repo

    async def build_status_text(self) -> str:
        state = await self.state_repo.get()
        pending = await self.video_repo.pending_count()

        next_at = as_utc(state.next_post_at)
        if next_at is not None:
            delta = (next_at - now_utc()).total_seconds()
            eta = "maintenant" if delta <= 0 else _fmt_eta(delta)
        else:
            eta = "—"

        return (
            "📊 <b>État du bot</b>\n"
            f"{'⏸️ EN PAUSE' if state.paused else '▶️ ACTIF'}\n\n"
            f"<b>En file :</b> {pending}\n"
            f"<b>Publiées :</b> {state.total_published}\n"
            f"<b>Échecs :</b> {state.total_failed}\n"
            f"<b>Détectées (total) :</b> {state.total_ingested}\n"
            f"<b>Prochain post :</b> {eta}\n"
            f"<b>Dernier post :</b> "
            f"{state.last_published_at.strftime('%Y-%m-%d %H:%M UTC') if state.last_published_at else '—'}"
        )


def _fmt_eta(seconds: float) -> str:
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"dans {h}h{m:02d}"
    if m:
        return f"dans {m}min"
    return f"dans {s}s"
