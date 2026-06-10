"""
Modèle Video : la pièce maîtresse de la persistance.

Chaque vidéo détectée dans un canal devient une ligne ici. Le statut + les
compteurs permettent une reprise EXACTE après crash/redémarrage. Le champ
`tg_file_unique_id` (stable côté Telegram) sert de clé anti-doublon principale ;
`sha256` sert de clé anti-doublon secondaire (contenu identique reposté).
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import VideoStatus
from app.models.base import Base


class Video(Base):
    __tablename__ = "videos"
    __table_args__ = (
        UniqueConstraint("tg_file_unique_id", name="uq_videos_file_unique_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # ── Provenance Telegram ───────────────────────────────────────────────────
    tg_file_unique_id: Mapped[str] = mapped_column(String(128), index=True)
    tg_file_id: Mapped[str] = mapped_column(String(256))
    tg_chat_id: Mapped[int] = mapped_column(BigInteger)
    tg_message_id: Mapped[int] = mapped_column(BigInteger)
    source_channel: Mapped[str | None] = mapped_column(String(255), nullable=True)
    original_caption: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── État ──────────────────────────────────────────────────────────────────
    status: Mapped[VideoStatus] = mapped_column(
        Enum(VideoStatus, native_enum=False, length=24),
        default=VideoStatus.PENDING,
        index=True,
    )
    # Ordre FIFO stable (séquence d'arrivée).
    queue_seq: Mapped[int] = mapped_column(BigInteger, index=True)

    # ── Fichier local & intégrité ─────────────────────────────────────────────
    file_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    file_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    duration: Mapped[float | None] = mapped_column(Float, nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # ── Résultat X ────────────────────────────────────────────────────────────
    x_tweet_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    x_media_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    published_caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # ── Robustesse ────────────────────────────────────────────────────────────
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
