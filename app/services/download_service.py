"""
DownloadService : télécharge un média Telegram vers le disque.

⚠️ Limite importante : l'API Bot standard ne permet de télécharger que des
fichiers ≤ 20 Mo (getFile). Au-delà, il faut un **serveur Bot API local**
(variable TELEGRAM_API_URL) qui lève la limite à 2 Go. Le service détecte le cas
et lève une erreur explicite (capturée en amont) plutôt que d'échouer obscurément.
"""
from __future__ import annotations

from pathlib import Path

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError

from app.config import get_settings
from app.core.exceptions import DownloadError, FileTooLargeError
from app.core.interfaces import IDownloader
from app.utils.logging_config import get_logger

log = get_logger("download")


class DownloadService(IDownloader):
    def __init__(self, bot: Bot) -> None:
        self.bot = bot
        self.settings = get_settings()

    async def download(self, *, file_id: str, dest: Path, expected_size: int | None) -> Path:
        """Télécharge `file_id` vers `dest`. Lève DownloadError/FileTooLargeError."""
        dest.parent.mkdir(parents=True, exist_ok=True)

        has_local_server = bool(self.settings.telegram_api_url)
        limit = self.settings.telegram_download_limit_bytes
        if not has_local_server and expected_size and expected_size > limit:
            raise FileTooLargeError(
                f"{expected_size} octets > limite Bot API {limit} (serveur local requis)"
            )

        try:
            await self.bot.download(file_id, destination=dest)
        except TelegramBadRequest as exc:
            text = str(exc).lower()
            if "too big" in text or "file is too big" in text:
                raise FileTooLargeError(str(exc)) from exc
            raise DownloadError(f"bad_request: {exc}") from exc
        except TelegramNetworkError as exc:
            raise DownloadError(f"network: {exc}") from exc
        except Exception as exc:  # noqa: BLE001
            raise DownloadError(f"unexpected: {exc}") from exc

        # Vérification minimale immédiate.
        if not dest.exists() or dest.stat().st_size == 0:
            raise DownloadError("fichier vide ou absent après téléchargement")

        log.info("download.ok", file=str(dest), size=dest.stat().st_size)
        return dest
