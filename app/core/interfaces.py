"""
Contrats abstraits (ABC) — cœur de l'inversion de dépendances.

Les services concrets implémentent ces interfaces ; le conteneur d'injection les
assemble. Cela permet de remplacer une implémentation (ex: file DB ↔ Redis,
publisher X ↔ mock de test) sans toucher au reste du code.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Protocol

from app.utils.files import FileIntegrity


class IQueueBackend(ABC):
    """File d'attente durable des vidéos à publier (FIFO)."""

    @abstractmethod
    async def enqueue(self, video_id: int) -> None: ...

    @abstractmethod
    async def next_ready(self) -> int | None:
        """Renvoie l'id de la prochaine vidéo publiable, sans la retirer."""

    @abstractmethod
    async def size(self) -> int: ...


class IDownloader(ABC):
    """Téléchargement d'un média Telegram vers un fichier local."""

    @abstractmethod
    async def download(self, *, file_id: str, dest: Path, expected_size: int | None) -> Path: ...


class IVerifier(ABC):
    """Vérification d'intégrité d'un fichier média."""

    @abstractmethod
    async def verify(self, path: Path, *, require_video: bool = True) -> FileIntegrity | None: ...


class IPublisher(ABC):
    """Publication d'une vidéo sur la plateforme cible (X)."""

    @abstractmethod
    async def healthcheck(self) -> bool:
        """Vérifie la validité des credentials et la connexion."""

    @abstractmethod
    async def publish_video(self, *, path: Path, caption: str) -> str:
        """Publie la vidéo, renvoie l'id du post créé. Lève en cas d'échec."""


class INotifier(Protocol):
    """Canal de notification (monitoring) — typé en Protocol pour souplesse."""

    async def notify(self, text: str) -> None: ...
