"""
Hiérarchie d'exceptions métier.

On distingue clairement :
  - les erreurs RÉESSAYABLES (réseau, rate-limit, serveur X temporairement KO),
  - les erreurs DÉFINITIVES (token invalide, contenu refusé, doublon),
afin que le système de retry n'insiste que quand cela a du sens.
"""
from __future__ import annotations


class PosterError(Exception):
    """Racine de toutes les erreurs applicatives."""


# ── Réessayables ──────────────────────────────────────────────────────────────
class RetryableError(PosterError):
    """Erreur temporaire : une nouvelle tentative est pertinente."""


class NetworkError(RetryableError):
    pass


class RateLimitError(RetryableError):
    """Rate-limit X. Peut porter un délai d'attente imposé."""

    def __init__(self, message: str = "rate limited", retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class TemporaryXError(RetryableError):
    """Erreur 5xx côté X."""


class DownloadError(RetryableError):
    pass


# ── Définitives ───────────────────────────────────────────────────────────────
class FatalError(PosterError):
    """Erreur définitive : inutile de réessayer."""


class InvalidCredentialsError(FatalError):
    """Token/secret X invalide ou compte non autorisé."""


class AccountSuspendedError(FatalError):
    pass


class ContentRejectedError(FatalError):
    """X refuse le contenu (doublon, format, politique…)."""


class IntegrityError(FatalError):
    """Le fichier a échoué la vérification d'intégrité."""


class FileTooLargeError(FatalError):
    """Fichier au-delà des limites téléchargeables/postables, non compressible."""


class DuplicateVideoError(PosterError):
    """La vidéo a déjà été vue (file_unique_id ou checksum connu)."""
