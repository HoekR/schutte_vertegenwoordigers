#!/usr/bin/env zsh
# Deploy lemma_extractor/_site to the gh-pages branch.
# Usage: ./deploy.sh [optional commit message]
set -e

REPO="$(git rev-parse --show-toplevel)"
SITE="$REPO/lemma_extractor/_site"
DEPLOY="$REPO/_deploy"
MSG="${1:-Deploy: $(date '+%Y-%m-%d %H:%M')}"

echo "==> Cleaning up any stale worktree..."
rm -rf "$DEPLOY"
git -C "$REPO" worktree prune

echo "==> Creating deploy worktree on gh-pages..."
git -C "$REPO" worktree add -B gh-pages "$DEPLOY" origin/gh-pages

echo "==> Syncing site files..."
rsync -a --delete "$SITE/" "$DEPLOY/"

echo "==> Committing..."
git -C "$DEPLOY" add -A
if git -C "$DEPLOY" diff --cached --quiet; then
  echo "Nothing to deploy — site is already up to date."
else
  git -C "$DEPLOY" commit -m "$MSG"
  echo "==> Pushing to origin/gh-pages..."
  git -C "$DEPLOY" push origin HEAD:gh-pages
  echo "==> Deployed: $MSG"
fi

echo "==> Cleaning up worktree..."
rm -rf "$DEPLOY"
git -C "$REPO" worktree prune
echo "Done."
