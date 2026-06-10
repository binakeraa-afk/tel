"""Repository de base : reçoit l'instance Database (injection de dépendance)."""
from __future__ import annotations

from app.db.engine import Database


class BaseRepository:
    def __init__(self, db: Database) -> None:
        self.db = db
