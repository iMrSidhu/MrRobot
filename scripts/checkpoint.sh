#!/usr/bin/env bash
# Usage: scripts/checkpoint.sh <step-id> '<message>'
# Runs tests (if any), commits everything, tags an restore point, pushes if origin exists.
set -euo pipefail
cd "$(dirname "$0")/.."

STEP="${1:?usage: checkpoint.sh <step-id> '<message>'}"
MSG="${2:?usage: checkpoint.sh <step-id> '<message>'}"

# Test gate: abort before committing if tests fail.
if [ -d tests ] || compgen -G "test_*.py" >/dev/null; then
  python -m pytest -q
fi

git add -A
# Windows checkouts have no exec bit; keep the workflow scripts executable in the repo.
git update-index --chmod=+x scripts/checkpoint.sh scripts/rollback.sh 2>/dev/null || true
if ! git diff --cached --quiet; then
  git commit -m "step ${STEP}: ${MSG}"
fi

TAG="restore/${STEP}"
n=1
while git rev-parse -q --verify "refs/tags/${TAG}" >/dev/null; do
  n=$((n + 1)); TAG="restore/${STEP}-r${n}"
done
git tag -a "${TAG}" -m "${MSG}"

# Push branch + tag if origin is configured; never die on network/auth problems.
if git remote get-url origin >/dev/null 2>&1; then
  export GIT_TERMINAL_PROMPT=0
  git -c credential.interactive=false push origin HEAD || echo "WARNING: branch push failed (offline/no access) — tag stays local"
  git -c credential.interactive=false push origin "refs/tags/${TAG}" || echo "WARNING: tag push failed — tag stays local"
fi

echo "${TAG}"
