#!/usr/bin/env bash
# Usage: scripts/rollback.sh <tag>   (e.g. scripts/rollback.sh restore/07)
# Non-destructive: saves uncommitted work on a backup branch, then checks out a new
# branch from the tag. Never touches main, never deletes anything.
set -euo pipefail
cd "$(dirname "$0")/.."

TAG="${1:?usage: rollback.sh <tag>}"
git rev-parse -q --verify "refs/tags/${TAG}" >/dev/null || { echo "ERROR: no such tag: ${TAG}"; exit 1; }

# 1) Preserve any uncommitted work at current HEAD on a throwaway branch.
if [ -n "$(git status --porcelain)" ]; then
  TS="$(date +%Y%m%d-%H%M%S)"
  git checkout -b "backup/${TS}"
  git add -A
  git commit -m "backup: uncommitted work before rollback to ${TAG}"
  echo "Uncommitted work saved on branch backup/${TS}"
fi

# 2) Branch off the tag and check it out.
BRANCH="rollback/${TAG}"
if git rev-parse -q --verify "refs/heads/${BRANCH}" >/dev/null; then
  BRANCH="${BRANCH}-$(date +%Y%m%d-%H%M%S)"
fi
git checkout -b "${BRANCH}" "refs/tags/${TAG}"

cat <<EOF

Now on '${BRANCH}' (from tag '${TAG}'); main is untouched.
To make main point to this state:
    git branch -f main ${BRANCH}
    git checkout main
Note: publishing that to origin would need a force-push, which AGENT_PROTOCOL.md forbids —
keep main local at the rollback point or revert forward instead.
EOF
