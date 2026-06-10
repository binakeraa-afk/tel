"""
Modèle SystemState : état global du planificateur (ligne unique, id=1).

C'est CE qui rend la planification résiliente au redémarrage : `next_post_at` est
persisté, donc après un crash le bot reprend le décompte exactement où il en était.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class SystemState(Base):
    __tablename__ = "system_state"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)

    # Prochaine date de publication autorisée (UTC).
    next_post_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Pause globale (commande admin /pause).
    paused: Mapped[bool] = mapped_column(Boolean, default=False)

    # Compteurs de monitoring.
    total_published: Mapped[int] = mapped_column(Integer, default=0)
    total_failed: Mapped[int] = mapped_column(Integer, default=0)
    total_ingested: Mapped[int] = mapped_column(Integer, default=0)
    last_published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Séquence FIFO globale (incrémentée à chaque ingestion).
    queue_counter: Mapped[int] = mapped_column(BigInteger, default=0)

    # Cookies de session X (mode unofficial/twikit), JSON sérialisé. Persistés ici
    # pour survivre aux redéploiements et éviter de se reconnecter trop souvent
    # (chaque reconnexion augmente le risque de challenge/blocage côté X).
    x_cookies_json: Mapped[str | None] = mapped_column(Text, nullable=True)
