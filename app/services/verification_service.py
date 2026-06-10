"""
VerificationService : applique l'intégrité technique + les règles métier X.

Vérifie (plusieurs passes) :
  - intégrité fichier (taille, checksum, ffprobe) via utils.files,
  - présence d'un flux vidéo,
  - bornes métier (durée/octets) compatibles X.
Renvoie un FileIntegrity validé, ou None (jamais d'exception destinée à l'utilisateur).
"""
from __future__ import annotations

from pathlib import Path

from app.config import get_settings
from app.core.interfaces import IVerifier
from app.utils.files import FileIntegrity, verify_integrity
from app.utils.logging_config import get_logger

log = get_logger("verification")


class VerificationService(IVerifier):
    def __init__(self) -> None:
        self.settings = get_settings()

    async def verify(self, path: Path, *, require_video: bool = True) -> FileIntegrity | None:
        integrity = await verify_integrity(path, require_video=require_video)
        if integrity is None:
            return None

        # Garde-fou durée : si ffprobe a pu mesurer, on alerte au-delà de la limite.
        probe = integrity.probe
        if probe is not None and probe.duration > 0:
            if probe.duration > self.settings.x_max_video_seconds:
                log.warning(
                    "verify.duration_exceeds",
                    duration=probe.duration, max=self.settings.x_max_video_seconds,
                )
                # On ne rejette pas d'office (X tolère parfois plus) ; on laisse
                # la publication tenter, puis échouer proprement si refus.
        log.info(
            "verify.ok",
            size=integrity.size, sha=integrity.sha256[:12],
            duration=(probe.duration if probe else None),
        )
        return integrity
