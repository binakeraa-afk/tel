"""
Middleware d'accès aux commandes admin (messages privés).

Appliqué uniquement à l'observateur `message` (pas aux `channel_post`). Si
ADMIN_USER_IDS est défini, seuls ces utilisateurs peuvent parler au bot ; les
autres sont ignorés silencieusement.
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from app.config import get_settings
from app.utils.logging_config import get_logger

log = get_logger("access")


class AccessMiddleware(BaseMiddleware):
    def __init__(self) -> None:
        self.admin_ids = get_settings().admin_ids

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not self.admin_ids:
            return await handler(event, data)
        user = data.get("event_from_user")
        if user is None or user.id not in self.admin_ids:
            log.debug("access.denied", user_id=getattr(user, "id", None))
            return None
        return await handler(event, data)
