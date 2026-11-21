# AI Diagram Studio — single-container build (backend + renderer + static frontend).
# NOTE: verified for correctness by review only; `docker compose up --build`
# has NOT been executed in this environment (no Docker available) — see
# IMPLEMENTATION_REPORT.md Phase 1 section.
FROM node:20-bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
      python3 python3-pip python3-venv \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /studio

# Python deps first for layer caching.
COPY backend/requirements.txt /studio/backend/requirements.txt
RUN pip3 install --break-system-packages --no-cache-dir -r /studio/backend/requirements.txt

# Renderer + frontend deps.
COPY renderer/package.json renderer/package-lock.json /studio/renderer/
COPY frontend/package.json /studio/frontend/
RUN cd /studio/renderer && npm ci \
    && cd /studio/frontend && npm install

COPY . /studio

RUN cd /studio/renderer && npm run build \
    && cd /studio/frontend && npm run build

ENV STORAGE_ROOT=/data/storage \
    DATABASE_PATH=/data/storage/studio.db \
    LLM_ENABLED=false \
    RENDERER_CLI=/studio/renderer/dist/src/cli.js \
    ICONS_DIR=/studio/renderer/assets/icons \
    FRONTEND_DIST=/studio/frontend/dist

VOLUME ["/data/storage"]
EXPOSE 8000

WORKDIR /studio/backend
CMD ["python3", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
