# The Hangul API (FastAPI). The web app has its own image: web/Dockerfile.
# docker-compose.prod.yml runs both behind Caddy; see docs/deploy.md.

# ---- Stage 1: builder — installs dependencies into a venv ----
FROM python:3.12-slim AS builder

# Don't write .pyc files; stream logs unbuffered
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# gcc is needed to build some Python packages; removed after (it's not in the final image)
RUN apt-get update && apt-get install -y --no-install-recommends gcc \
    && rm -rf /var/lib/apt/lists/*

# Create a virtual environment we'll copy to the runtime stage
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install deps first (this layer caches — only re-runs when pyproject changes)
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir .

# ---- Stage 2: runtime — the small final image ----
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# Node: MCP servers declared in servers.yaml run through npx
# fonts-dejavu-core: a Unicode font for generated PDFs (create_file: ₹, accents, Greek, Cyrillic)
# curl: the health check
RUN apt-get update && apt-get install -y --no-install-recommends nodejs npm fonts-dejavu-core curl \
    && rm -rf /var/lib/apt/lists/*

# Copy the ready-made venv from the builder (no build tools shipped)
COPY --from=builder /opt/venv /opt/venv

# The application, its migrations, and the shared documents (indexed into
# Postgres with `python -m harness.retrieval.ingest docs`, once per database)
COPY src ./src
COPY alembic ./alembic
COPY alembic.ini ./
COPY docs ./docs
COPY start.sh ./

# The user files folder lives on a volume (data/sessions); a non-root user owns it
RUN mkdir -p data/sessions && \
    groupadd -r app && useradd -r -g app -m -d /home/app app && \
    mkdir -p /home/app/.npm && \
    chown -R app:app /app /home/app && chmod +x start.sh
ENV HOME=/home/app \
    NPM_CONFIG_CACHE=/home/app/.npm
USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD curl -fsS http://localhost:8000/healthz >/dev/null || exit 1

# Migrations (RUN_MIGRATIONS=1, the default), then the API (start.sh)
CMD ["./start.sh"]
