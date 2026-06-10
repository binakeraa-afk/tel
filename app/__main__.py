"""
Point d'entrée : python -m app

Séquence : logging → conteneur (DI) → dispatcher + injection des services dans les
handlers → hooks de cycle de vie (start/stop) → long-polling Telegram.
"""
from __future__ import annotations

import asyncio

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from app.container import Container
from app.handlers import setup_handlers
from app.utils.logging_config import get_logger, setup_logging


async def _set_commands(bot: Bot) -> None:
    try:
        await bot.set_my_commands([
            BotCommand(command="status", description="État & file d'attente"),
            BotCommand(command="next", description="Publier maintenant"),
            BotCommand(command="pause", description="Suspendre"),
            BotCommand(command="resume", description="Reprendre"),
            BotCommand(command="id", description="Afficher les identifiants"),
            BotCommand(command="help", description="Aide"),
        ])
    except Exception as exc:  # noqa: BLE001
        get_logger("startup").warning("set_commands_failed", error=repr(exc))


async def main() -> None:
    setup_logging()
    log = get_logger("main")
    log.info("boot.start", version="1.0.0")

    container = Container()
    bot = container.bot

    dp = Dispatcher(storage=MemoryStorage())
    # Injection des services dans les handlers (DI via workflow_data).
    dp["ingest"] = container.ingest
    dp["monitoring"] = container.monitoring
    dp["scheduler"] = container.scheduler
    dp["state_repo"] = container.state_repo
    setup_handlers(dp)

    async def on_startup() -> None:
        await container.start()
        await _set_commands(bot)
        await container.notifier.notify("🤖 <b>Bot démarré</b> et prêt.")
        log.info("boot.ready")

    async def on_shutdown() -> None:
        log.info("shutdown.start")
        await container.stop()
        log.info("shutdown.done")

    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    try:
        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types(),
            handle_signals=True,
        )
    except Exception as exc:  # noqa: BLE001
        log.error("polling.crashed", error=repr(exc), exc_info=True)
        raise


def run() -> None:
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass


if __name__ == "__main__":
    run()
