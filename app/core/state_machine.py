"""
Machine à états des vidéos.

Centralise les transitions VALIDES pour empêcher des incohérences (ex: publier
une vidéo non vérifiée). Toute transition illégale est journalisée et rejetée,
sans lever d'exception destinée à l'utilisateur.
"""
from __future__ import annotations

from app.core.enums import VideoStatus
from app.utils.logging_config import get_logger

log = get_logger("state_machine")

# Graphe des transitions autorisées.
_ALLOWED: dict[VideoStatus, set[VideoStatus]] = {
    VideoStatus.PENDING: {VideoStatus.DOWNLOADING, VideoStatus.SKIPPED_DUPLICATE, VideoStatus.FAILED},
    VideoStatus.DOWNLOADING: {VideoStatus.DOWNLOADED, VideoStatus.FAILED, VideoStatus.PENDING},
    VideoStatus.DOWNLOADED: {VideoStatus.VERIFYING, VideoStatus.FAILED},
    VideoStatus.VERIFYING: {VideoStatus.READY, VideoStatus.FAILED},
    VideoStatus.READY: {VideoStatus.PUBLISHING, VideoStatus.FAILED},
    VideoStatus.PUBLISHING: {VideoStatus.PUBLISHED, VideoStatus.READY, VideoStatus.FAILED},
    # États terminaux : aucune transition sortante.
    VideoStatus.PUBLISHED: set(),
    VideoStatus.FAILED: {VideoStatus.PENDING},  # un admin peut relancer
    VideoStatus.SKIPPED_DUPLICATE: set(),
}


class StateMachine:
    @staticmethod
    def can_transition(current: VideoStatus, target: VideoStatus) -> bool:
        return target in _ALLOWED.get(current, set())

    @staticmethod
    def validate(current: VideoStatus, target: VideoStatus) -> bool:
        """Valide une transition ; log et renvoie False si illégale."""
        if current == target:
            return True
        ok = StateMachine.can_transition(current, target)
        if not ok:
            log.warning("state.illegal_transition", current=current.value, target=target.value)
        return ok
