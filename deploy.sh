#!/usr/bin/env zsh
# Deploy lemma_extractor/_site to the gh-pages branch.
# Uses a temp dir completely outside the repo to avoid worktree/branch confusion.
# Usage: ./deploy.sh [optional commit message]
set -e

REPO="$(git rev-parse --show-toplevel)"
SITE="$REPO/lemma_extractor/_site"
REMOTE="$(git -C "$REPO" remote get-url origin)"
MSG="${1:-Deploy: $(date '+%Y-%m-%d %H:%M')}"
TMP="$(mktemp -d)"

echo "==> Cloning gh-pages into temp dir..."
git clone --branch gh-pages --single-branch "$REMOTE" "$TMP"

echo "==> Syncing site files..."
rsync -a --delete --exclude='.git' "$SITE/" "$TMP/"

echo "==> Committing..."
git -C "$TMP" add -A
if git -C "$TMP" diff --cached --quiet; then
  echo "Nothing to deploy — site is already up to date."
else
  git -C "$TMP" commit -m "$MSG"
  echo "==> Pushing to origin/gh-pages..."
  git -C "$TMP" push origin gh-pages
  echo "==> Deployed: $MSG"
fi

echo "==> Cleaning up..."
rm -rf "$TMP"
echo "Done."
