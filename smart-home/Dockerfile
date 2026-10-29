# syntax=docker/dockerfile:1

FROM node:22-bookworm-slim AS frontend-build
WORKDIR /build
ENV NEXT_TELEMETRY_DISABLED=1 \
    NEXT_PUBLIC_API_URL= \
    API_TARGET=http://backend:8000
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM node:22-bookworm-slim AS dashboard
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    HOSTNAME=0.0.0.0 \
    PORT=3000
COPY --from=frontend-build --chown=node:node /build/.next/standalone ./
COPY --from=frontend-build --chown=node:node /build/.next/static ./.next/static
COPY --from=frontend-build --chown=node:node /build/public ./public
USER node
EXPOSE 3000
CMD ["node", "server.js"]

FROM python:3.13-slim-bookworm AS backend
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    YOLO_AUTOINSTALL=false \
    YOLO_CONFIG_DIR=/tmp/ultralytics \
    MPLCONFIGDIR=/tmp/matplotlib \
    FALL_DEVICE=cuda:0
WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends adb libgl1 libglib2.0-0 libgomp1 \
    && rm -rf /var/lib/apt/lists/*
COPY backend/requirements.txt backend/requirements-fall.txt ./
# Matching PyTorch/torchvision wheels include the CUDA 12.8 runtime libraries.
RUN pip install --no-cache-dir torch==2.7.1 torchvision==0.22.1 --index-url https://download.pytorch.org/whl/cu128 \
    && pip install --no-cache-dir -r requirements-fall.txt
COPY backend/app/ ./app/
COPY backend/fallguard/ ./fallguard/
COPY docker/start_backend.py ./docker/start_backend.py
RUN useradd --create-home --uid 10001 app \
    && mkdir -p /data /app/models /app/tools/adb \
    && chown app:app /data
USER app
EXPOSE 8000
CMD ["python", "docker/start_backend.py"]
