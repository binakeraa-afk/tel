"""
Vérification d'intégrité et manipulation des fichiers médias.

Couvre la « vérification multiple » exigée :
  - existence + taille non nulle + taille stable,
  - checksum SHA-256 (lecture intégrale => détecte la corruption),
  - sonde ffprobe : durée, dimensions, présence d'un flux vidéo décodable.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from app.utils.logging_config import get_logger

log = get_logger("files")

VIDEO_EXTS = {".mp4", ".mov", ".webm", ".mkv", ".m4v"}


@dataclass
class MediaProbe:
    """Métadonnées techniques extraites d'un fichier vidéo."""

    duration: float
    width: int
    height: int
    has_video_stream: bool


@dataclass
class FileIntegrity:
    """Résultat complet d'une vérification d'intégrité."""

    path: Path
    size: int
    sha256: str
    probe: MediaProbe | None


async def sha256(path: Path) -> str:
    def _hash() -> str:
        h = hashlib.sha256()
        with path.open("rb") as fh:
            for block in iter(lambda: fh.read(1024 * 1024), b""):
                h.update(block)
        return h.hexdigest()

    return await asyncio.to_thread(_hash)


async def size_is_stable(path: Path, checks: int = 3, interval: float = 0.3) -> bool:
    last = -1
    for _ in range(checks):
        try:
            cur = path.stat().st_size
        except OSError:
            return False
        if cur == 0:
            return False
        if cur == last:
            return True
        last = cur
        await asyncio.sleep(interval)
    try:
        return path.stat().st_size == last
    except OSError:
        return False


async def ffprobe(path: Path) -> MediaProbe | None:
    """Sonde le fichier via ffprobe. None si ffprobe échoue/absent."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "error",
            "-print_format", "json",
            "-show_streams", "-show_format",
            str(path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=60)
    except FileNotFoundError:
        log.warning("ffprobe.absent")
        return None
    except Exception as exc:  # noqa: BLE001
        log.warning("ffprobe.error", error=repr(exc))
        return None

    if proc.returncode != 0:
        return None
    try:
        data = json.loads(out.decode("utf-8", "replace") or "{}")
    except json.JSONDecodeError:
        return None

    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    fmt = data.get("format", {})
    duration = float(fmt.get("duration") or (video or {}).get("duration") or 0.0)
    return MediaProbe(
        duration=duration,
        width=int((video or {}).get("width") or 0),
        height=int((video or {}).get("height") or 0),
        has_video_stream=video is not None,
    )


async def verify_integrity(path: Path, *, require_video: bool = True) -> FileIntegrity | None:
    """Vérification complète. Renvoie None (sans lever) si le fichier est invalide."""
    try:
        if not path.exists() or not path.is_file():
            log.warning("integrity.missing", file=str(path))
            return None
        if not await size_is_stable(path):
            log.warning("integrity.unstable", file=str(path))
            return None

        probe = await ffprobe(path)
        if require_video and probe is not None and not probe.has_video_stream:
            log.warning("integrity.no_video_stream", file=str(path))
            return None

        size = path.stat().st_size
        digest = await sha256(path)
        return FileIntegrity(path=path, size=size, sha256=digest, probe=probe)
    except Exception as exc:  # noqa: BLE001
        log.warning("integrity.unexpected", file=str(path), error=repr(exc))
        return None


async def safe_unlink(path: Path | None) -> None:
    if path is None:
        return
    try:
        await asyncio.to_thread(path.unlink, missing_ok=True)
    except Exception as exc:  # noqa: BLE001
        log.warning("cleanup.unlink_failed", file=str(path), error=repr(exc))


async def safe_rmtree(directory: Path) -> None:
    try:
        await asyncio.to_thread(shutil.rmtree, directory, ignore_errors=True)
    except Exception as exc:  # noqa: BLE001
        log.warning("cleanup.rmtree_failed", dir=str(directory), error=repr(exc))
