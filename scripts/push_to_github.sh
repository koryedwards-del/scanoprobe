#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

REPO_NAME="scanoprobe"
MAX_WAIT=600
INTERVAL=5
elapsed=0

echo "Waiting for GitHub authorization (up to ${MAX_WAIT}s)..."
while ! gh auth status >/dev/null 2>&1; do
  sleep "$INTERVAL"
  elapsed=$((elapsed + INTERVAL))
  if (( elapsed >= MAX_WAIT )); then
    echo "Timed out waiting for gh auth."
    exit 1
  fi
done

echo "GitHub authenticated as: $(gh api user -q .login)"

if git show-ref --verify --quiet refs/heads/main; then
  git checkout main
else
  git branch -M main
fi

if gh repo view "$REPO_NAME" >/dev/null 2>&1; then
  echo "Repo $REPO_NAME already exists; pushing."
  git remote get-url origin >/dev/null 2>&1 || git remote add origin "https://github.com/$(gh api user -q .login)/${REPO_NAME}.git"
else
  gh repo create "$REPO_NAME" --private --source=. --remote=origin --description "Personal Burn & Build LBA — BodyMetrix probe reader"
fi

git push -u origin main
echo "DONE: https://github.com/$(gh api user -q .login)/${REPO_NAME}"
