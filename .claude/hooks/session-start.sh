#!/bin/bash
# Bootstraps a Claude Code on the web session so the verify checks run immediately,
# without the session first discovering that uv is missing or dependencies are not
# installed. Idempotent and non-interactive.
set -euo pipefail

# Only bootstrap remote sessions. A local machine already has its environment.
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}"

# uv is not preinstalled on the cloud VM. Install it if missing, then keep it on PATH for
# the rest of this hook and for the session that follows.
if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
export PATH="$HOME/.local/bin:$PATH"
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$CLAUDE_ENV_FILE"
fi

# Backend, including the dev group (ruff, mypy, pytest) the verify skill needs.
(cd backend && uv python install && uv sync --frozen)

# Frontend, from the lockfile.
(cd frontend && npm ci)
