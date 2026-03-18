#!/bin/zsh
set -euo pipefail

REPO_DIR="/Users/namanchetwani/Projects/Osu"
cd "$REPO_DIR"

# Ensure Homebrew and user bin paths are available under launchd.
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$HOME/.local/bin:$PATH"

if [ -f ".venv/bin/activate" ]; then
  source ".venv/bin/activate"
fi

if [ -f ".env.local" ]; then
  set -a
  source ".env.local"
  set +a
fi

# Non-interactive Codex execution prevents TTY prompt failures in service mode.
export OSU_CODEX_CMD="codex -a never exec"

exec python -m host.server
