"""
Handler des publications de canal : détecte les nouvelles vidéos.

Le bot doit être ADMIN du/des canal(aux) surveillé(s) pour recevoir les updates
`channel_post`. On filtre par liste blanche de canaux (SOURCE_CHANNELS) si fournie,
sinon on accepte tout canal où le bot est admin.
"""
from __future__ import annotations

from aiogram import Router
from aiogram.types import Message

from app.config import get_settings
from app.services.ingest_service import IngestService
from app.utils.logging_config import get_logger

router = Router(name="channel_posts")
log = get_logger("handlers.channel")


def _wanted(message: Message) -> bool:
    """Filtre : message d'un canal surveillé contenant une vidéo exploitable."""
    s = get_settings()
    allowed = s.source_channel_set
    if allowed:
        candidates = {str(message.chat.id).lower()}
        if message.chat.username:
            candidates.add(message.chat.username.lower())
        if not (candidates & allowed):
            return False
    return IngestService._extract_media(message) is not None


@router.channel_post(_wanted)
async def on_channel_video(message: Message, ingest: IngestService) -> None:
    accepted = await ingest.register(message)
    if accepted:
        log.info("channel.video_accepted", chat_id=message.chat.id, msg_id=message.message_id)
