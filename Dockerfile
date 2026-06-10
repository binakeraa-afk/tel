# ──────────────────────────────────────────────────────────────────────────────
#  Dockerfile multi-stage optimisé pour Railway.
#  Stage builder : compile les dépendances dans un venv isolé.
#  Stage runtime : image légère + ffmpeg (probe & compression).
# ──────────────────────────────────────────────────────────────────────────────

FROM python:3.11-slim AS builder

ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt


FROM python:3.11-slim AS runtime

# ffmpeg/ffprobe : vérification d'intégrité + compression intelligente.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 10001 appuser

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONFAULTHANDLER=1

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY . .

RUN mkdir -p /app/data && chown -R appuser:appuser /app
USER appuser

HEALTHCHECK --interval=60s --timeout=10s --start-period=20s --retries=3 \
    CMD python -c "import sys; sys.exit(0)"

# Migrations (si présentes) puis lancement. Le `sh -c` interprète le `if`.
CMD ["sh", "-c", "if [ -d alembic ]; then alembic upgrade head || true; fi; python -m app"]
