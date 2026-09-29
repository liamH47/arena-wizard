# syntax=docker/dockerfile:1
#
# Three stages: build the React app, build the Python environment, then a slim runtime
# holding only the virtual environment and the built frontend. The container runs as a
# non-root user and starts through the entrypoint, which waits for the database, migrates,
# then serves (decision 0008). Never point uvicorn at arena_wizard.main directly: that
# would skip the wait and the migration.

FROM node:24-alpine AS frontend-build
WORKDIR /frontend
# Manifests first, so a source-only change reuses the dependency layer.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim AS backend-build
# Pinned to the uv that wrote uv.lock and that CI uses.
COPY --from=ghcr.io/astral-sh/uv:0.11.16 /uv /uvx /usr/local/bin/
# Compile bytecode now: a free instance has about a tenth of a CPU, and compiling at the
# first import added 20 to 30 seconds to every cold start (event-night reliability).
# Use the image's own Python, which the runtime stage shares, never a downloaded one.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /build
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/src ./src
# Non-editable: the package, with its configs, card tables, and migrations, is installed
# into the virtual environment, so the runtime needs no source tree.
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.13-slim AS runtime
RUN groupadd --system app \
    && useradd --system --gid app --create-home --home-dir /home/app --shell /usr/sbin/nologin app
WORKDIR /app
COPY --from=backend-build --chown=app:app /app/.venv /app/.venv
COPY --from=frontend-build --chown=app:app /frontend/dist /app/static
# PYTHONUNBUFFERED so the entrypoint's "database not ready" lines reach Render's log while
# it waits, not after. Bytecode stays on: it was compiled in the build stage.
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    ARENA_WIZARD_STATIC_DIR=/app/static \
    HOME=/home/app \
    PORT=8000
USER app
EXPOSE 8000
# The entrypoint reads $PORT; Render injects its own and expects the process to bind it.
CMD ["python", "-m", "arena_wizard.entrypoint"]
