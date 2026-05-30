#!/usr/bin/env bash
# Create a locked Stratum release tag from the current development tree.

set -euo pipefail

usage() {
  echo "Usage: $0 VERSION"
  echo "Example: $0 v0.7.0"
}

if [[ $# -ne 1 ]]; then
  usage
  exit 2
fi

VERSION="$1"
if [[ ! "$VERSION" =~ ^v[0-9]+\.[0-9]+\.[0-9]+([.-][A-Za-z0-9]+)?$ ]]; then
  echo "❌ Version must look like v0.7.0 or v0.7.0-rc1"
  exit 2
fi

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -n "$(git status --porcelain)" ]]; then
  echo "❌ Refusing to release from a dirty worktree."
  echo "   Commit or stash development changes first."
  exit 1
fi

if git rev-parse -q --verify "refs/tags/$VERSION" >/dev/null; then
  echo "❌ Tag already exists: $VERSION"
  exit 1
fi

PYTHON="${PYTHON:-}"
if [[ -z "$PYTHON" ]]; then
  if [[ -x ".venv/bin/python" ]]; then
    PYTHON=".venv/bin/python"
  else
    PYTHON="python3"
  fi
fi

echo "🔎 Running release test suite..."
"$PYTHON" -m pytest -q

COMMIT="$(git rev-parse HEAD)"
git tag -a "$VERSION" -m "Release $VERSION"

echo "✅ Release tag created"
echo "   version: $VERSION"
echo "   commit:  $COMMIT"
echo ""
echo "Next:"
echo "   git push origin main --tags"
