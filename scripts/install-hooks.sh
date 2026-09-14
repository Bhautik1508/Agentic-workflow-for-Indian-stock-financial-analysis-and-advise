#!/usr/bin/env bash
# Install the repo's git hooks. Safe to re-run.
set -euo pipefail
ROOT=$(git rev-parse --show-toplevel)
install -m 0755 "$ROOT/scripts/pre-commit" "$ROOT/.git/hooks/pre-commit"
echo "[ok] installed .git/hooks/pre-commit"
command -v gitleaks >/dev/null 2>&1 \
  && echo "[ok] gitleaks detected - it will run as an extra layer" \
  || echo "[note] gitleaks not installed (optional): brew install gitleaks"
