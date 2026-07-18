# Stage 1: Build Layer
FROM python:3.12-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_INSTALL_DIR=/app/.uv-python \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

COPY pyproject.toml uv.lock ./
RUN uv sync --no-dev

COPY . .
ENV DJANGO_SETTINGS_MODULE=config.settings
RUN OIDC_RP_CLIENT_ID=builder OIDC_RP_CLIENT_SECRET=builder OIDC_RP_CALLBACK_URL=builder \
    uv run python manage.py collectstatic --noinput

# Stage 2: Hardened Execution Runtime
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --system --gid 1001 appgroup && \
    adduser --system --uid 1001 --gid 1001 --no-create-home appuser

COPY --from=builder --chown=appuser:appgroup /app /app

ENV PATH="/app/.venv/bin:$PATH" \
    DJANGO_SETTINGS_MODULE=config.settings \
    PYTHONUNBUFFERED=1

COPY --chown=appuser:appgroup docker-entrypoint.sh /
RUN chmod +x /docker-entrypoint.sh

USER appuser
ENTRYPOINT ["/docker-entrypoint.sh"]
