"""
Configuration centralisée et typée (12-factor).

Toute la configuration vient de l'environnement et est validée au démarrage :
une mauvaise config fait échouer le boot immédiatement (seule erreur « visible »
tolérée, car c'est une erreur opérateur, pas utilisateur).
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ── Telegram ──────────────────────────────────────────────────────────────
    bot_token: str = Field(..., alias="BOT_TOKEN")
    # Canaux surveillés : ids (-100…) ou @usernames, séparés par des virgules.
    # Vide => le bot accepte tout canal où il est admin.
    source_channels: str = Field(default="", alias="SOURCE_CHANNELS")
    # Chat privé recevant le monitoring / les commandes admin.
    admin_chat_id: int | None = Field(default=None, alias="ADMIN_CHAT_ID")
    admin_user_ids: str = Field(default="", alias="ADMIN_USER_IDS")
    # Serveur Bot API local optionnel (lève la limite de 20 Mo à 2 Go).
    telegram_api_url: str | None = Field(default=None, alias="TELEGRAM_API_URL")

    # ── X / Twitter ───────────────────────────────────────────────────────────
    # Mode d'accès :
    #   "unofficial" (défaut) → twikit, connexion avec ton COMPTE X (sans compte
    #                           développeur). ⚠️ Contraire aux CGU de X (risque de
    #                           suspension). À utiliser en connaissance de cause.
    #   "official"            → API X officielle via Tweepy (clés développeur).
    x_mode: Literal["unofficial", "official"] = Field(default="unofficial", alias="X_MODE")

    # ── Mode "unofficial" (twikit — compte X classique) ───────────────────────
    x_username: str = Field(default="", alias="X_USERNAME")          # @handle sans @
    x_email: str = Field(default="", alias="X_EMAIL")
    x_password: str = Field(default="", alias="X_PASSWORD")
    x_totp_secret: str | None = Field(default=None, alias="X_TOTP_SECRET")  # 2FA TOTP
    # Cookies optionnels (JSON) pour éviter une reconnexion (réduit le risque).
    x_cookies: str | None = Field(default=None, alias="X_COOKIES")

    # ── Mode "official" (Tweepy — OAuth 1.0a, compte développeur) ─────────────
    x_consumer_key: str = Field(default="", alias="X_CONSUMER_KEY")
    x_consumer_secret: str = Field(default="", alias="X_CONSUMER_SECRET")
    x_access_token: str = Field(default="", alias="X_ACCESS_TOKEN")
    x_access_token_secret: str = Field(default="", alias="X_ACCESS_TOKEN_SECRET")
    x_bearer_token: str | None = Field(default=None, alias="X_BEARER_TOKEN")

    # ── Base de données ───────────────────────────────────────────────────────
    database_url: str = Field(
        default="sqlite+aiosqlite:///./data/poster.db", alias="DATABASE_URL"
    )

    # ── File d'attente ────────────────────────────────────────────────────────
    # "db" (par défaut, résilient, zéro service externe) ou "redis".
    queue_backend: Literal["db", "redis"] = Field(default="db", alias="QUEUE_BACKEND")
    redis_url: str | None = Field(default=None, alias="REDIS_URL")

    # ── Planning de publication ───────────────────────────────────────────────
    # Intervalle entre deux posts (secondes). 3 h par défaut.
    post_interval_seconds: int = Field(default=3 * 3600, alias="POST_INTERVAL_SECONDS")
    # Fréquence de réveil du planificateur (vérifie si un post est dû).
    scheduler_tick_seconds: int = Field(default=60, alias="SCHEDULER_TICK_SECONDS")
    # Fenêtre horaire autorisée (heures UTC) : ne poste qu'entre ces heures.
    # 0/24 = aucune restriction.
    active_hour_start: int = Field(default=0, alias="ACTIVE_HOUR_START")
    active_hour_end: int = Field(default=24, alias="ACTIVE_HOUR_END")

    # ── Fichiers / médias ─────────────────────────────────────────────────────
    work_dir: Path = Field(default=Path("./data/media"), alias="WORK_DIR")
    log_dir: Path = Field(default=Path("./data/logs"), alias="LOG_DIR")
    # Limites X pour la vidéo.
    x_max_video_bytes: int = Field(default=512 * 1024 * 1024, alias="X_MAX_VIDEO_BYTES")
    x_max_video_seconds: int = Field(default=140, alias="X_MAX_VIDEO_SECONDS")
    # Seuil de déclenchement de la compression (octets).
    compress_threshold_bytes: int = Field(
        default=64 * 1024 * 1024, alias="COMPRESS_THRESHOLD_BYTES"
    )
    # Limite de téléchargement Bot API standard (20 Mo). Au-delà, nécessite un
    # serveur Bot API local (voir TELEGRAM_API_URL).
    telegram_download_limit_bytes: int = Field(
        default=20 * 1024 * 1024, alias="TELEGRAM_DOWNLOAD_LIMIT_BYTES"
    )

    # ── Retry / robustesse ────────────────────────────────────────────────────
    max_retries: int = Field(default=7, alias="MAX_RETRIES")
    retry_base_delay: float = Field(default=2.0, alias="RETRY_BASE_DELAY")
    retry_max_delay: float = Field(default=300.0, alias="RETRY_MAX_DELAY")

    # ── Légende automatique ───────────────────────────────────────────────────
    # Modèle de légende. Variables: {caption} {channel} {index} {date}
    caption_template: str = Field(default="{caption}", alias="CAPTION_TEMPLATE")
    default_hashtags: str = Field(default="", alias="DEFAULT_HASHTAGS")

    # ── Logging ───────────────────────────────────────────────────────────────
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(
        default="INFO", alias="LOG_LEVEL"
    )
    log_json: bool = Field(default=True, alias="LOG_JSON")

    # ── Validateurs ───────────────────────────────────────────────────────────
    @field_validator("work_dir", "log_dir")
    @classmethod
    def _ensure_dir(cls, v: Path) -> Path:
        v.mkdir(parents=True, exist_ok=True)
        return v

    # ── Dérivés ───────────────────────────────────────────────────────────────
    @property
    def admin_ids(self) -> set[int]:
        out: set[int] = set()
        for chunk in self.admin_user_ids.split(","):
            chunk = chunk.strip()
            if chunk.lstrip("-").isdigit():
                out.add(int(chunk))
        return out

    @property
    def source_channel_set(self) -> set[str]:
        """Ensemble normalisé d'identifiants de canaux surveillés (str)."""
        return {c.strip().lstrip("@").lower() for c in self.source_channels.split(",") if c.strip()}

    @property
    def hashtags_suffix(self) -> str:
        tags = [t.strip() for t in self.default_hashtags.split(",") if t.strip()]
        tags = [t if t.startswith("#") else f"#{t}" for t in tags]
        return (" " + " ".join(tags)) if tags else ""

    @property
    def is_postgres(self) -> bool:
        return self.database_url.startswith("postgres")

    @property
    def x_configured(self) -> bool:
        """True si le mode officiel (Tweepy) dispose de toutes ses clés."""
        return all(
            [
                self.x_consumer_key,
                self.x_consumer_secret,
                self.x_access_token,
                self.x_access_token_secret,
            ]
        )

    @property
    def x_ready(self) -> bool:
        """True si la configuration X du mode actif est suffisante pour publier."""
        if self.x_mode == "official":
            return self.x_configured
        # unofficial : cookies fournis, OU username + password.
        return bool(self.x_cookies or (self.x_username and self.x_password))


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
