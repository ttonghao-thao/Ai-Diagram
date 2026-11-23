# AI Diagram Studio — single-container build (backend + renderer + static frontend).
#
# Build & run (from the repository root):
#   docker build -f deploy/Dockerfile -t ai-diagram-studio .
#   docker run -p 8000:8000 -v ai-diagram-data:/data/storage ai-diagram-studio
# Or: cd deploy && cp env.example .env && docker compose up --build
#
# STATUS: reviewed line-by-line and hardened (npm ci everywhere, .dockerignore,
# HEALTHCHECK), but an actual `docker compose up --build` has NOT been executed
# on the development machine (no Docker available). See docs/09_DEPLOYMENT.md.
FROM node:20-bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
      python3 python3-pip python3-venv \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /studio

# Python dependencies first for layer caching.
COPY backend/requirements.txt /studio/backend/requirements.txt
RUN pip3 install --break-system-packages --no-cache-dir -r /studio/backend/requirements.txt

# Renderer + frontend dependencies: npm ci everywhere so builds are locked to
# the committed package-lock.json files.
COPY renderer/package.json renderer/package-lock.json /studio/renderer/
COPY frontend/package.json frontend/package-lock.json /studio/frontend/
RUN cd /studio/renderer && npm ci \
    && cd /studio/frontend && npm ci

COPY . /studio

RUN cd /studio/renderer && npm run build \
    && cd /studio/frontend && npm run build

ENV STORAGE_ROOT=/data/storage \
    DATABASE_PATH=/data/storage/studio.db \
    LLM_ENABLED=false \
    LLM_PROVIDER=mock \
    RENDERER_CLI=/studio/renderer/dist/src/cli.js \
    ICONS_DIR=/studio/renderer/assets/icons \
    FRONTEND_DIST=/studio/frontend/dist

VOLUME ["/data/storage"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python3 -c "import urllib.request,sys;sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=3).status==200 else 1)"

WORKDIR /studio/backend
CMD ["python3", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
