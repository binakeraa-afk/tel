"""Énumérations du domaine."""
from __future__ import annotations

import enum


class VideoStatus(str, enum.Enum):
    """Cycle de vie d'une vidéo, de la détection à la publication.

    Transitions valides définies dans core.state_machine.
    """

    PENDING = "pending"            # détectée, en file d'attente
    DOWNLOADING = "downloading"    # téléchargement en cours
    DOWNLOADED = "downloaded"      # fichier présent localement
    VERIFYING = "verifying"        # vérification d'intégrité
    READY = "ready"                # vérifiée, prête à publier
    PUBLISHING = "publishing"      # publication X en cours
    PUBLISHED = "published"        # publiée avec succès (terminal)
    FAILED = "failed"              # échec définitif (terminal, après retries)
    SKIPPED_DUPLICATE = "skipped_duplicate"  # doublon détecté (terminal)


# États « terminaux » : ne seront plus traités par le planificateur.
TERMINAL_STATUSES = {
    VideoStatus.PUBLISHED,
    VideoStatus.FAILED,
    VideoStatus.SKIPPED_DUPLICATE,
}

# États « prêts à publier ».
PUBLISHABLE_STATUSES = {VideoStatus.READY, VideoStatus.DOWNLOADED}


class MediaSourceType(str, enum.Enum):
    VIDEO = "video"
    DOCUMENT_VIDEO = "document_video"
    ANIMATION = "animation"
