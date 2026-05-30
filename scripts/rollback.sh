#!/usr/bin/env bash
# Move an environment's current symlink back to an already deployed release.

set -euo pipefail

usage() {
  echo "Usage: $0 --root DEPLOY_ROOT --env production --version v0.7.0"
}

DEPLOY_ROOT=""
ENV_NAME=""
VERSION=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --root) DEPLOY_ROOT="${2:-}"; shift 2 ;;
    --env) ENV_NAME="${2:-}"; shift 2 ;;
    --version) VERSION="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "❌ Unknown argument: $1"; usage; exit 2 ;;
  esac
done

if [[ -z "$DEPLOY_ROOT" || -z "$ENV_NAME" || -z "$VERSION" ]]; then
  usage
  exit 2
fi

DEPLOY_BASE="$DEPLOY_ROOT/$ENV_NAME"
RELEASE_DIR="$DEPLOY_BASE/releases/$VERSION"
RELEASE_MANIFEST="$RELEASE_DIR/deployment_manifest.json"
MANIFEST="$DEPLOY_BASE/deployment_manifest.json"
CURRENT="$DEPLOY_BASE/current"

if [[ ! -d "$RELEASE_DIR" || ! -f "$RELEASE_MANIFEST" ]]; then
  echo "❌ Release is not deployed locally: $RELEASE_DIR"
  exit 1
fi

PREVIOUS_VERSION=""
if [[ -f "$MANIFEST" ]]; then
  PREVIOUS_VERSION="$(python3 - "$MANIFEST" <<'PY'
import json, sys
try:
    with open(sys.argv[1]) as f:
        print(json.load(f).get("version", ""))
except Exception:
    print("")
PY
)"
fi

python3 - "$RELEASE_MANIFEST" "$MANIFEST" "$PREVIOUS_VERSION" <<'PY'
import json, sys
src, dst, previous = sys.argv[1], sys.argv[2], sys.argv[3]
with open(src) as f:
    manifest = json.load(f)
manifest["status"] = "active"
manifest["rollback_from"] = previous
manifest["rolled_back_at"] = __import__("datetime").datetime.utcnow().isoformat() + "Z"
with open(dst, "w") as f:
    json.dump(manifest, f, ensure_ascii=False, indent=2)
PY

ln -sfn "$RELEASE_DIR" "$CURRENT"

echo "✅ Rollback active"
echo "   env:     $ENV_NAME"
echo "   version: $VERSION"
echo "   current: $CURRENT -> $RELEASE_DIR"
