# Hybrid Windows image: Next.js ONLY (no Python, AI, CUDA, or ADB in Docker).
FROM node:22-bookworm-slim AS frontend-build
WORKDIR /build
ARG API_TARGET=http://host.docker.internal:8000
ENV NEXT_TELEMETRY_DISABLED=1 \
    NEXT_PUBLIC_API_URL= \
    API_TARGET=${API_TARGET}
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
