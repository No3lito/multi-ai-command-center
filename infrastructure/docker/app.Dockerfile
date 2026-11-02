# Single image: builds the dashboard (static export) and serves it from the FastAPI backend,
# so the browser talks to one origin for pages, API and WebSockets.

# ---- dashboard build ----
FROM node:22-bookworm-slim AS web
WORKDIR /web
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY apps/web/ ./
RUN npm run build

# ---- backend ----
FROM python:3.12-slim-bookworm AS app
COPY --from=ghcr.io/astral-sh/uv:0.11.32 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    WEB_DIST=/srv/web
WORKDIR /srv/backend

COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/ ./
RUN uv sync --frozen --no-dev
COPY packages/ /srv/packages/
COPY --from=web /web/out /srv/web

RUN useradd --system --uid 10001 --home /srv app && chown -R app /srv
USER app

EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health').status == 200 else 1)"

# Apply migrations, then serve. Binds 0.0.0.0 inside the container only; Compose publishes it on 127.0.0.1.
CMD ["sh", "-c", "command-center migrate && exec uvicorn command_center.main:app --host 0.0.0.0 --port 8000 --no-server-header --no-proxy-headers"]
