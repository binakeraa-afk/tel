"""Handler d'erreurs global : filet ultime, aucune stacktrace exposée."""
from __future__ import annotations

from aiogram import Router
from aiogram.types import ErrorEvent

from app.utils.logging_config import get_logger

router = Router(name="errors")
log = get_logger("handlers.errors")


@router.errors()
async def on_error(event: ErrorEvent) -> bool:
    log.error(
        "handler.exception",
        error=repr(event.exception),
        update_id=getattr(event.update, "update_id", None),
        exc_info=True,
    )
    return True  # erreur « avalée » : rien ne fuit
