"""
Logging structuré (structlog) + rotation de fichiers.

- Sortie stdout en JSON (LOG_JSON=true) pour l'agrégateur Railway.
- Fichier tournant (RotatingFileHandler) dans LOG_DIR pour conserver un historique
  local consultable (sur le volume persistant).
- ⚠️ On n'utilise PAS `add_logger_name` (incompatible avec PrintLogger qui n'a pas
  d'attribut .name). Le nom du logger est injecté via get_logger(name).bind(...).
"""
from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

import structlog

from app.config import get_settings


def setup_logging() -> None:
    settings = get_settings()
    level = getattr(logging, settings.log_level, logging.INFO)

    shared_processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    renderer: structlog.typing.Processor = (
        structlog.processors.JSONRenderer()
        if settings.log_json
        else structlog.dev.ConsoleRenderer(colors=True)
    )

    structlog.configure(
        processors=shared_processors + [renderer],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )

    # Stdlib : stdout + fichier tournant.
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    stream = logging.StreamHandler(sys.stderr)
    stream.setFormatter(logging.Formatter("%(message)s"))
    root.addHandler(stream)

    try:
        file_handler = RotatingFileHandler(
            settings.log_dir / "poster.log",
            maxBytes=5 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setFormatter(logging.Formatter("%(message)s"))
        root.addHandler(file_handler)
    except Exception:  # noqa: BLE001 — un échec de fichier ne doit pas bloquer
        pass

    for noisy in ("aiosqlite", "asyncio", "aiogram.event", "apscheduler.executors"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("tweepy").setLevel(logging.WARNING)


def get_logger(name: str | None = None):
    logger = structlog.get_logger()
    return logger.bind(logger=name) if name else logger
