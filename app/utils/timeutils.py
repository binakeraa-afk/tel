"""
Utilitaires de temps.

Point clé de robustesse : SQLite ne stocke pas les fuseaux et renvoie des
datetimes « naïfs ». Comparer un datetime naïf avec un datetime aware lève une
TypeError. `as_utc` garantit qu'on manipule TOUJOURS de l'UTC aware.
"""
from __future__ import annotations

from datetime import datetime, timezone


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(dt: datetime | None) -> datetime | None:
    """Normalise un datetime en UTC aware. None reste None."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
