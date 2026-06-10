"""
Branchement des routeurs et middlewares.

  - AccessMiddleware sur `message` uniquement (commandes admin), pas sur les
    `channel_post` (sinon on bloquerait l'ingestion des vidéos).
  - Ordre des routeurs : erreurs → admin → channel.
"""
from __future__ import annotations

from aiogram import Dispatcher

from app.handlers import admin_commands, channel_posts, errors
from app.middlewares import AccessMiddleware


def setup_handlers(dp: Dispatcher) -> None:
    dp.message.middleware(AccessMiddleware())

    dp.include_router(errors.router)
    dp.include_router(admin_commands.router)
    dp.include_router(channel_posts.router)
