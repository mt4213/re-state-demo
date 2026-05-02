#!/usr/bin/env bash
# Push the local demo branch to the public re-state-demo repo.
# Run this after merging changes from master into demo.
set -euo pipefail

REMOTE=demo-public
BRANCH=demo

if ! git remote get-url "$REMOTE" &>/dev/null; then
  echo "Adding remote $REMOTE..."
  git remote add "$REMOTE" https://github.com/mt4213/re-state-demo.git
fi

echo "Pushing $BRANCH -> $REMOTE/main..."
git push "$REMOTE" "$BRANCH:main"
echo "Done: https://github.com/mt4213/re-state-demo"
