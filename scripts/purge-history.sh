#!/usr/bin/env bash
# Rewrite git history to remove the committed .env blob and the vendored venv.
#
# READ THIS FIRST
# ---------------
# Rotating the keys is the actual fix. A secret that was pushed is public the
# moment it lands; purging history only stops it being re-scraped later. Do
# Phase 0 rotation FIRST, verify with `python scripts/audit_secrets.py`, then
# run this for hygiene.
#
# This rewrites every commit SHA. Consequences:
#   - requires a force-push to a public repo
#   - anyone with a clone or fork must re-clone; their old SHAs are gone
#   - open PRs against the old history will break
#
# This script NEVER pushes. It prints the push command and stops, so the
# irreversible step stays a deliberate act.
#
# Usage:
#   bash scripts/purge-history.sh            # dry run — shows what would go
#   bash scripts/purge-history.sh --execute  # rewrite LOCAL history only

set -euo pipefail

RED=$'\033[0;31m'; YEL=$'\033[0;33m'; GRN=$'\033[0;32m'; OFF=$'\033[0m'
ROOT=$(git rev-parse --show-toplevel)
cd "$ROOT"

EXECUTE=0
[ "${1:-}" = "--execute" ] && EXECUTE=1

TARGETS=(backend/.env backend/venv)

echo "Repository: $ROOT"
echo "Paths to purge from ALL history:"
for t in "${TARGETS[@]}"; do
  n=$(git rev-list --all --objects -- "$t" 2>/dev/null | wc -l | tr -d ' ')
  echo "  - $t  (~$n objects in history)"
done
echo
echo "Current .git size: $(du -sh .git | cut -f1)"
echo

if ! command -v git-filter-repo >/dev/null 2>&1; then
  echo "${RED}git-filter-repo is not installed.${OFF}"
  echo "  brew install git-filter-repo      # or: pipx install git-filter-repo"
  echo
  echo "Do NOT substitute 'git filter-branch' — it is slow, error-prone, and"
  echo "misses refs that filter-repo handles correctly."
  exit 2
fi

if [ "$EXECUTE" -ne 1 ]; then
  echo "${YEL}DRY RUN.${OFF} Nothing changed. To rewrite local history:"
  echo "  bash scripts/purge-history.sh --execute"
  exit 0
fi

# Refuse to run with uncommitted work — filter-repo requires a clean tree and
# a rewrite over a dirty tree is a good way to lose work.
if [ -n "$(git status --porcelain)" ]; then
  echo "${RED}Working tree is not clean.${OFF} Commit or stash first."
  exit 1
fi

BACKUP="../$(basename "$ROOT")-backup-$(date +%Y%m%d-%H%M%S).git"
echo "Creating mirror backup at: $BACKUP"
git clone --mirror . "$BACKUP" >/dev/null 2>&1
echo "${GRN}[ok]${OFF} backup created"
echo

ARGS=()
for t in "${TARGETS[@]}"; do ARGS+=(--path "$t"); done
git-filter-repo "${ARGS[@]}" --invert-paths --force

echo
echo "${GRN}[ok]${OFF} local history rewritten. New .git size: $(du -sh .git | cut -f1)"
echo
echo "${YEL}Not pushed.${OFF} Review, then push deliberately:"
echo
echo "  git remote add origin <your-repo-url>   # filter-repo drops the remote"
echo "  git push --force --all origin"
echo "  git push --force --tags origin"
echo
echo "Afterwards: tell anyone with a clone to re-clone, and confirm the keys"
echo "were rotated —  python scripts/audit_secrets.py"
