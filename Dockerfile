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

# Node is needed for the MCP filesystem server (npx @modelcontextprotocol/server-filesystem)
# fonts-dejavu-core: a Unicode font for generated PDFs (create_file: ₹, accents, Greek, Cyrillic)
RUN apt-get update && apt-get install -y --no-install-recommends nodejs npm fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# Copy the ready-made venv from the builder (no build tools shipped)
COPY --from=builder /opt/venv /opt/venv

# Copy the application code and data the app reads
COPY src ./src
COPY docs ./docs
COPY data/index.json data/index_version.txt ./data/
COPY data/eval_runs ./data/eval_runs
COPY data/eval_baseline.json ./data/
COPY streamlit_app.py ./
COPY .streamlit ./.streamlit
COPY start.sh ./

# Create the session folder the app writes to, and a non-root user
RUN mkdir -p data/sessions && \
    groupadd -r app && useradd -r -g app -m -d /home/app app && \
    mkdir -p /home/app/.npm && \
    chown -R app:app /app /home/app
ENV HOME=/home/app \
    NPM_CONFIG_CACHE=/home/app/.npm
USER app

# API on 8000, Streamlit on 8501
EXPOSE 8000 8501

# Health check: is the API answering? (slim image has no curl, so use python)
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz').read()" || exit 1

# Start both processes (see start.sh)
CMD ["./start.sh"]
