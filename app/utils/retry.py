"""
Retry maison : backoff exponentiel + full jitter, jusqu'à 7 tentatives.

- Respecte un délai imposé par le serveur (rate-limit X, Retry-After).
- Distingue les exceptions « réessayables » des exceptions « définitives ».
- À l'épuisement, lève RetryExhausted (toujours capturé en amont, jamais visible).
"""
from __future__ import annotations

import asyncio
import functools
import random
from typing import Awaitable, Callable, Iterable, TypeVar

from app.config import get_settings
from app.utils.logging_config import get_logger

log = get_logger("retry")
T = TypeVar("T")


class RetryExhausted(Exception):
    def __init__(self, attempts: int, last_exc: BaseException) -> None:
        super().__init__(f"Échec après {attempts} tentative(s) : {last_exc!r}")
        self.attempts = attempts
        self.last_exc = last_exc


def extract_retry_after(exc: BaseException) -> float | None:
    """Extrait un délai imposé par le serveur depuis l'exception, si présent."""
    # Tweepy TooManyRequests expose la réponse HTTP avec l'en-tête reset.
    resp = getattr(exc, "response", None)
    if resp is not None:
        headers = getattr(resp, "headers", {}) or {}
        for key in ("retry-after", "x-rate-limit-reset"):
            val = headers.get(key)
            if val:
                try:
                    num = float(val)
                    # x-rate-limit-reset est un timestamp epoch.
                    if key == "x-rate-limit-reset":
                        import time
                        return max(0.0, num - time.time())
                    return num
                except (TypeError, ValueError):
                    continue
    for attr in ("retry_after", "timeout"):
        v = getattr(exc, attr, None)
        if isinstance(v, (int, float)) and v > 0:
            return float(v)
    return None


def _delay(attempt: int, base: float, cap: float) -> float:
    return random.uniform(0, min(cap, base * (2 ** attempt)))


async def retry_call(
    func: Callable[..., Awaitable[T]],
    *args,
    retry_on: Iterable[type[BaseException]] = (Exception,),
    give_up_on: Iterable[type[BaseException]] = (),
    max_attempts: int | None = None,
    base_delay: float | None = None,
    max_delay: float | None = None,
    op_name: str = "operation",
    **kwargs,
) -> T:
    s = get_settings()
    attempts = max_attempts or s.max_retries
    base = base_delay if base_delay is not None else s.retry_base_delay
    cap = max_delay if max_delay is not None else s.retry_max_delay
    retry_on, give_up_on = tuple(retry_on), tuple(give_up_on)
    last_exc: BaseException = RuntimeError("aucune tentative")

    for attempt in range(attempts):
        try:
            return await func(*args, **kwargs)
        except give_up_on as exc:  # type: ignore[misc]
            log.warning("retry.give_up", op=op_name, error=repr(exc))
            raise
        except retry_on as exc:  # type: ignore[misc]
            last_exc = exc
            forced = extract_retry_after(exc)
            delay = forced if forced is not None else _delay(attempt, base, cap)
            is_last = attempt == attempts - 1
            log.warning(
                "retry.attempt_failed",
                op=op_name, attempt=attempt + 1, max_attempts=attempts,
                delay=round(delay, 2), forced=forced is not None,
                error=repr(exc), will_retry=not is_last,
            )
            if is_last:
                break
            await asyncio.sleep(delay)
    raise RetryExhausted(attempts, last_exc)


def async_retry(
    *,
    retry_on: Iterable[type[BaseException]] = (Exception,),
    give_up_on: Iterable[type[BaseException]] = (),
    max_attempts: int | None = None,
    op_name: str | None = None,
):
    def decorator(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        name = op_name or func.__name__

        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> T:
            return await retry_call(
                func, *args, retry_on=retry_on, give_up_on=give_up_on,
                max_attempts=max_attempts, op_name=name, **kwargs,
            )

        return wrapper

    return decorator
