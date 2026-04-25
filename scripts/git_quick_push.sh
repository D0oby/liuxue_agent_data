#!/usr/bin/env bash

set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: ./scripts/git_quick_push.sh \"your commit message\""
  exit 1
fi

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
commit_message="$*"

cd "$repo_root"

echo "== Git status =="
git status -sb

echo
echo "== Staging changes =="
git add .

if git diff --cached --quiet; then
  echo "No staged changes found. Nothing to commit."
  exit 0
fi

echo
echo "== Creating commit =="
git commit -m "$commit_message"

echo
echo "== Pushing to origin =="
git push

echo
echo "Done."
