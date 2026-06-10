"""
Commandes admin (monitoring & contrôle), en message privé.

  /start, /help  — aide
  /status        — état (file, publiés, échecs, prochain créneau)
  /pause /resume — suspendre / reprendre la publication
  /next          — forcer une publication immédiate
  /id            — afficher les ids (utile pour configurer SOURCE_CHANNELS / ADMIN)

L'accès est restreint par AccessMiddleware (liste ADMIN_USER_IDS).
"""
from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from app.db.repositories import StateRepository
from app.schedulers import PostingScheduler
from app.services.monitoring_service import MonitoringService
from app.utils.logging_config import get_logger

router = Router(name="admin")
log = get_logger("handlers.admin")

_HELP = (
    "🤖 <b>Bot Telegram → X (auto-poster)</b>\n\n"
    "Je surveille le(s) canal(aux) configuré(s), récupère les vidéos et les publie "
    "sur X selon le planning (1 toutes les 3 h par défaut).\n\n"
    "<b>Commandes</b>\n"
    "• /status — état & file d'attente\n"
    "• /pause — suspendre la publication\n"
    "• /resume — reprendre\n"
    "• /next — publier maintenant\n"
    "• /id — afficher les identifiants\n"
)


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    await message.answer(_HELP)


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(_HELP)


@router.message(Command("status"))
async def cmd_status(message: Message, monitoring: MonitoringService) -> None:
    await message.answer(await monitoring.build_status_text())


@router.message(Command("pause"))
async def cmd_pause(message: Message, state_repo: StateRepository) -> None:
    await state_repo.set_paused(True)
    await message.answer("⏸️ Publication <b>en pause</b>.")


@router.message(Command("resume"))
async def cmd_resume(message: Message, state_repo: StateRepository) -> None:
    await state_repo.set_paused(False)
    await message.answer("▶️ Publication <b>reprise</b>.")


@router.message(Command("next"))
async def cmd_next(message: Message, scheduler: PostingScheduler) -> None:
    await message.answer("⏳ Tentative de publication immédiate…")
    result = await scheduler.force_now()
    await message.answer(result)


@router.message(Command("id"))
async def cmd_id(message: Message) -> None:
    uid = message.from_user.id if message.from_user else "—"
    await message.answer(
        f"🆔 <b>chat_id</b> : <code>{message.chat.id}</code>\n"
        f"👤 <b>user_id</b> : <code>{uid}</code>"
    )
