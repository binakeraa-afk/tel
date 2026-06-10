"""
CompressionService : ré-encode une vidéo trop lourde via ffmpeg.

Stratégie « intelligente » par paliers : on tente des réglages de plus en plus
agressifs (résolution + CRF) jusqu'à passer sous le seuil cible, ou on abandonne
proprement (retour None). Le fichier d'origine n'est jamais modifié.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from app.utils.logging_config import get_logger

log = get_logger("compression")

# Paliers (hauteur max, CRF). CRF élevé => plus compressé / moins de qualité.
_LADDER = [(720, 28), (540, 30), (480, 32), (360, 34)]


class CompressionService:
    async def compress_to_fit(self, src: Path, target_bytes: int) -> Path | None:
        """Compresse `src` pour passer sous `target_bytes`. Renvoie un nouveau
        fichier, ou None si impossible/échec (capturé en amont)."""
        for height, crf in _LADDER:
            out = src.with_name(f"{src.stem}_c{height}.mp4")
            ok = await self._encode(src, out, height, crf)
            if ok and out.exists() and 0 < out.stat().st_size <= target_bytes:
                log.info("compress.ok", height=height, crf=crf, size=out.stat().st_size)
                return out
            # Nettoie l'essai raté avant le palier suivant.
            try:
                out.unlink(missing_ok=True)
            except OSError:
                pass
        log.warning("compress.failed", src=str(src), target=target_bytes)
        return None

    async def _encode(self, src: Path, out: Path, height: int, crf: int) -> bool:
        cmd = [
            "ffmpeg", "-y", "-i", str(src),
            "-vf", f"scale=-2:{height}",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf),
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            str(out),
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE
            )
            _, err = await asyncio.wait_for(proc.communicate(), timeout=60 * 20)
        except FileNotFoundError:
            log.warning("compress.ffmpeg_absent")
            return False
        except asyncio.TimeoutError:
            log.warning("compress.timeout", height=height)
            return False
        except Exception as exc:  # noqa: BLE001
            log.warning("compress.error", error=repr(exc))
            return False
        if proc.returncode != 0:
            log.warning("compress.nonzero", code=proc.returncode,
                        stderr=(err or b"").decode("utf-8", "replace")[-400:])
            return False
        return True
