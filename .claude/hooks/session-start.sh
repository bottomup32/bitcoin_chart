#!/bin/bash
# SessionStart hook — prepares the environment for Claude Code on the web.
#
# The repo holds two runtimes: the Python engine (core/agents/jobs, gated by CI)
# and the Next.js dashboard (app/components/lib). Both get their dependencies
# here so tests, linters and a dev server work from the first turn without a
# network round-trip mid-session.
#
# Idempotent: uv and npm both reuse the existing install on re-runs.
set -euo pipefail

# Local machines already have their own setup; only run in remote sessions.
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-$(dirname "$0")/../..}"

# --- Python engine -----------------------------------------------------------
# uv ships in the remote image, but fall back to the official installer.
if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi

# --frozen: honour uv.lock exactly; the dev group gives us pytest and ruff.
uv sync --frozen
echo "session-start: uv sync complete ($(uv run --frozen python -V))"

# --- Next.js dashboard -------------------------------------------------------
# Non-fatal: CI gates on the Python suite, so a node hiccup must not block the
# session. The warning tells the agent to run `npm install` before touching the
# dashboard rather than to trust a half-installed tree.
if [ -f package.json ] && command -v npm >/dev/null 2>&1; then
  if npm install --no-audit --no-fund; then
    echo "session-start: npm install complete ($(node -v))"
  else
    echo "session-start: WARNING npm install failed — run it by hand before touching app/, components/ or lib/" >&2
  fi
fi

# Make the venv the default interpreter for plain `python`/`pytest` calls too.
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  {
    echo "export PATH=\"$PWD/.venv/bin:\$PATH\""
    echo "export VIRTUAL_ENV=\"$PWD/.venv\""
  } >> "$CLAUDE_ENV_FILE"
fi
