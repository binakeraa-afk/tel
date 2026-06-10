"""
Décorateurs transverses : exécution silencieuse et mesure de durée.

`@silent` : capture toute exception, la journalise, et renvoie une valeur de repli.
Utilisé sur les chemins « best-effort » (monitoring, nettoyage, notifications)
pour garantir qu'aucune erreur ne fuit ni n'interrompt le flux principal.
"""
from __future__ import annotations

import functools
import time
from typing import Any, Awaitable, Callable, TypeVar

from app.utils.logging_config import get_logger

log = get_logger("decorators")
T = TypeVar("T")


def silent(default: Any = None, *, op: str | None = None):
    """Avale toute exception d'une coroutine, la log, renvoie `default`."""

    def decorator(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T | Any]]:
        name = op or func.__name__

        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001
                log.warning("silent.swallowed", op=name, error=repr(exc))
                return default

        return wrapper

    return decorator


def timed(op: str | None = None):
    """Journalise la durée d'exécution d'une coroutine (observabilité)."""

    def decorator(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        name = op or func.__name__

        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            start = time.monotonic()
            try:
                return await func(*args, **kwargs)
            finally:
                log.debug("timed", op=name, seconds=round(time.monotonic() - start, 3))

        return wrapper

    return decorator
