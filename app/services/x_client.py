"""
XClient : façade Tweepy pour publier une vidéo sur X.

Détails techniques :
  - Upload vidéo via l'API v1.1 `media_upload(chunked=True, media_category=
    'tweet_video')` qui gère INIT/APPEND/FINALIZE + l'attente du traitement async.
  - Création du tweet via l'API v2 `Client.create_tweet(media_ids=[...])`.
  - Authentification OAuth 1.0a user-context (consumer + access token) : c'est la
    voie la plus fiable pour l'upload vidéo. (Le bearer OAuth2 sert aux lectures.)
  - Tweepy est synchrone → tous les appels sont déportés dans un thread
    (`asyncio.to_thread`) pour ne pas bloquer la boucle asyncio.
  - Les exceptions Tweepy sont TRADUITES vers la hiérarchie métier (Retryable vs
    Fatal) afin que le retry n'insiste que quand c'est pertinent.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import tweepy

from app.config import get_settings
from app.core.exceptions import (
    AccountSuspendedError,
    ContentRejectedError,
    InvalidCredentialsError,
    NetworkError,
    RateLimitError,
    TemporaryXError,
)
from app.core.interfaces import IPublisher
from app.utils.logging_config import get_logger
from app.utils.retry import extract_retry_after

log = get_logger("x_client")


def _map_tweepy_error(exc: Exception) -> Exception:
    """Traduit une exception Tweepy vers la hiérarchie métier."""
    if isinstance(exc, tweepy.TooManyRequests):
        return RateLimitError("rate limited", retry_after=extract_retry_after(exc))
    if isinstance(exc, tweepy.Unauthorized):
        return InvalidCredentialsError(str(exc))
    if isinstance(exc, tweepy.Forbidden):
        text = str(exc).lower()
        if "suspend" in text:
            return AccountSuspendedError(str(exc))
        # Doublon, média invalide, politique… : définitif.
        return ContentRejectedError(str(exc))
    if isinstance(exc, tweepy.TwitterServerError):
        return TemporaryXError(str(exc))
    if isinstance(exc, (tweepy.BadRequest, tweepy.NotFound)):
        return ContentRejectedError(str(exc))
    if isinstance(exc, tweepy.TweepyException):
        # Inclut les erreurs de connexion sous-jacentes → réessayable.
        return NetworkError(str(exc))
    return NetworkError(repr(exc))


class XClient(IPublisher):
    def __init__(self) -> None:
        self.settings = get_settings()
        self._api: tweepy.API | None = None
        self._client: tweepy.Client | None = None

    # ── Construction paresseuse des clients Tweepy ─────────────────────────────
    def _ensure_clients(self) -> None:
        if self._api is not None and self._client is not None:
            return
        s = self.settings
        if not s.x_configured:
            raise InvalidCredentialsError("Identifiants X non configurés")
        auth = tweepy.OAuth1UserHandler(
            s.x_consumer_key, s.x_consumer_secret,
            s.x_access_token, s.x_access_token_secret,
        )
        # retry_count/delay gérés par NOTRE couche retry ; ici on garde simple.
        self._api = tweepy.API(auth, wait_on_rate_limit=False)
        self._client = tweepy.Client(
            consumer_key=s.x_consumer_key,
            consumer_secret=s.x_consumer_secret,
            access_token=s.x_access_token,
            access_token_secret=s.x_access_token_secret,
            wait_on_rate_limit=False,
        )

    # ── IPublisher ─────────────────────────────────────────────────────────────
    async def healthcheck(self) -> bool:
        """Vérifie credentials + connexion. Lève InvalidCredentialsError si KO."""
        def _check() -> bool:
            self._ensure_clients()
            assert self._api is not None
            user = self._api.verify_credentials()
            return bool(user)

        try:
            ok = await asyncio.to_thread(_check)
            log.info("x.healthcheck", ok=ok)
            return ok
        except Exception as exc:  # noqa: BLE001
            mapped = _map_tweepy_error(exc) if isinstance(exc, tweepy.TweepyException) else exc
            log.error("x.healthcheck_failed", error=repr(mapped))
            raise mapped

    async def publish_video(self, *, path: Path, caption: str) -> str:
        """Upload + tweet. Renvoie l'id du tweet. Lève (mappé) en cas d'échec."""
        media_id = await self._upload_video(path)
        tweet_id = await self._create_tweet(caption, media_id)
        log.info("x.published", tweet_id=tweet_id, media_id=media_id)
        return tweet_id

    # ── Étapes internes ────────────────────────────────────────────────────────
    async def _upload_video(self, path: Path) -> str:
        def _upload() -> str:
            self._ensure_clients()
            assert self._api is not None
            media = self._api.media_upload(
                filename=str(path),
                chunked=True,
                media_category="tweet_video",
                wait_for_async_finalize=True,
            )
            return str(media.media_id_string)

        try:
            return await asyncio.to_thread(_upload)
        except Exception as exc:  # noqa: BLE001
            raise _map_tweepy_error(exc) from exc

    async def _create_tweet(self, caption: str, media_id: str) -> str:
        def _tweet() -> str:
            self._ensure_clients()
            assert self._client is not None
            resp = self._client.create_tweet(text=caption, media_ids=[media_id])
            return str(resp.data["id"])

        try:
            return await asyncio.to_thread(_tweet)
        except Exception as exc:  # noqa: BLE001
            raise _map_tweepy_error(exc) from exc
