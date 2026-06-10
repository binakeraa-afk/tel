"""
TwikitPublisher : publication sur X SANS compte développeur.

Utilise la librairie `twikit` (client non-officiel, asynchrone) qui se connecte
avec les identifiants d'un compte X classique et imite le client web pour
uploader une vidéo et créer un tweet.

⚠️ AVERTISSEMENT : l'automatisation via un client non-officiel est CONTRAIRE aux
conditions d'utilisation de X et peut entraîner une suspension du compte. À
utiliser en connaissance de cause, sur un compte que tu maîtrises.

Robustesse :
  - Connexion paresseuse + verrou (une seule connexion concurrente).
  - Réutilisation des cookies persistés en base (évite de se reconnecter à chaque
    démarrage → réduit le risque de challenge/blocage).
  - En cas de session expirée, on se reconnecte automatiquement une fois.
  - Les exceptions twikit sont traduites vers la hiérarchie métier (Retryable/Fatal)
    par NOM de classe, pour rester robuste aux changements de versions.
"""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

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
from app.db.repositories import StateRepository
from app.utils.logging_config import get_logger

log = get_logger("twikit")


def _map_error(exc: Exception) -> Exception:
    """Traduit une exception twikit vers la hiérarchie métier (par nom de classe)."""
    name = type(exc).__name__
    msg = str(exc)
    if name == "TooManyRequests":
        retry_after = None
        reset = getattr(exc, "rate_limit_reset", None)
        try:
            if reset is not None:
                ts = reset.timestamp() if hasattr(reset, "timestamp") else float(reset)
                retry_after = max(0.0, ts - time.time())
        except Exception:  # noqa: BLE001
            retry_after = None
        return RateLimitError("rate limited", retry_after=retry_after)
    if name in ("Unauthorized", "AccountLocked"):
        return InvalidCredentialsError(msg)
    if name == "AccountSuspended":
        return AccountSuspendedError(msg)
    if name in ("Forbidden", "BadRequest", "NotFound"):
        return ContentRejectedError(msg)
    if name in ("ServerError", "RequestTimeout"):
        return TemporaryXError(msg)
    # Tout le reste (réseau, erreurs génériques twikit) → réessayable.
    return NetworkError(f"{name}: {msg}")


class TwikitPublisher(IPublisher):
    def __init__(self, state_repo: StateRepository) -> None:
        self.settings = get_settings()
        self.state_repo = state_repo
        self._client = None  # type: ignore[assignment]
        self._lock = asyncio.Lock()

    # ── Connexion ──────────────────────────────────────────────────────────────
    async def _ensure_client(self):
        if self._client is not None:
            return self._client
        async with self._lock:
            if self._client is not None:
                return self._client
            from twikit import Client  # import tardif (dépendance lourde)

            client = Client("en-US")

            # 1) Tente la réutilisation des cookies (base, sinon variable d'env).
            cookies_json = await self.state_repo.get_cookies() or self.settings.x_cookies
            if cookies_json:
                try:
                    client.set_cookies(json.loads(cookies_json))
                    await client.user()  # valide la session (lève si invalide)
                    self._client = client
                    log.info("twikit.session_restored")
                    return client
                except Exception as exc:  # noqa: BLE001
                    log.warning("twikit.cookies_invalid", error=repr(exc))

            # 2) Connexion par identifiants.
            if not (self.settings.x_username and self.settings.x_password):
                raise InvalidCredentialsError("X_USERNAME / X_PASSWORD manquants")

            kwargs = {
                "auth_info_1": self.settings.x_username,
                "password": self.settings.x_password,
            }
            if self.settings.x_email:
                kwargs["auth_info_2"] = self.settings.x_email
            if self.settings.x_totp_secret:
                kwargs["totp_secret"] = self.settings.x_totp_secret

            try:
                await client.login(**kwargs)
            except Exception as exc:  # noqa: BLE001
                raise _map_error(exc) from exc

            # Persiste les cookies pour les prochains démarrages.
            try:
                await self.state_repo.set_cookies(json.dumps(client.get_cookies()))
            except Exception as exc:  # noqa: BLE001
                log.warning("twikit.cookie_persist_failed", error=repr(exc))

            self._client = client
            log.info("twikit.logged_in", username=self.settings.x_username)
            return client

    def _invalidate(self) -> None:
        """Oublie le client (forcera une reconnexion au prochain appel)."""
        self._client = None

    # ── IPublisher ─────────────────────────────────────────────────────────────
    async def healthcheck(self) -> bool:
        client = await self._ensure_client()
        try:
            await client.user()
            log.info("twikit.healthcheck_ok")
            return True
        except Exception as exc:  # noqa: BLE001
            self._invalidate()
            raise _map_error(exc) from exc

    async def publish_video(self, *, path: Path, caption: str) -> str:
        client = await self._ensure_client()
        try:
            media_id = await client.upload_media(str(path), wait_for_completion=True)
            tweet = await client.create_tweet(text=caption, media_ids=[media_id])
            tweet_id = str(getattr(tweet, "id", "") or "")
            log.info("twikit.published", tweet_id=tweet_id)
            return tweet_id
        except Exception as exc:  # noqa: BLE001
            mapped = _map_error(exc)
            # Session expirée → on invalide pour reconnexion au prochain essai.
            if isinstance(mapped, InvalidCredentialsError):
                self._invalidate()
            raise mapped from exc
