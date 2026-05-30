#!/usr/bin/env bash
# Deploy a locked Stratum Git tag into an isolated deployment root.

set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  scripts/deploy.sh --version v0.7.0 --env production --domain storage \
    --root "$HOME/WorkSpace/Stratum/deployments" \
    --config /secure/stratum/config.yaml \
    --output-dir "$HOME/WorkSpace/Stratum/Reports"

Required:
  --version     Existing Git tag to deploy. Branches and bare commits are rejected.
  --env         Deployment environment name, e.g. staging or production.
  --domain      Domain id, e.g. storage.
  --root        Deployment root. Code releases live under <root>/<env>/releases/.
  --config      Instance config file. It is copied into <root>/<env>/config/.
  --output-dir  Report output root used by deployed runs.

Optional:
  --force       Replace an existing release directory for the same version.
USAGE
}

VERSION=""
ENV_NAME=""
DOMAIN=""
DEPLOY_ROOT=""
CONFIG_SRC=""
OUTPUT_DIR=""
FORCE=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --version) VERSION="${2:-}"; shift 2 ;;
    --env) ENV_NAME="${2:-}"; shift 2 ;;
    --domain) DOMAIN="${2:-}"; shift 2 ;;
    --root) DEPLOY_ROOT="${2:-}"; shift 2 ;;
    --config) CONFIG_SRC="${2:-}"; shift 2 ;;
    --output-dir) OUTPUT_DIR="${2:-}"; shift 2 ;;
    --force) FORCE=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "❌ Unknown argument: $1"; usage; exit 2 ;;
  esac
done

if [[ -z "$VERSION" || -z "$ENV_NAME" || -z "$DOMAIN" || -z "$DEPLOY_ROOT" || -z "$CONFIG_SRC" || -z "$OUTPUT_DIR" ]]; then
  usage
  exit 2
fi

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if ! git rev-parse -q --verify "refs/tags/$VERSION" >/dev/null; then
  echo "❌ Deployment requires an existing Git tag: $VERSION"
  exit 1
fi

if [[ ! -f "$CONFIG_SRC" ]]; then
  echo "❌ Config file not found: $CONFIG_SRC"
  exit 1
fi

COMMIT="$(git rev-list -n 1 "$VERSION")"
DEPLOY_BASE="$DEPLOY_ROOT/$ENV_NAME"
RELEASE_DIR="$DEPLOY_BASE/releases/$VERSION"
CONFIG_DIR="$DEPLOY_BASE/config"
CONFIG_DEST="$CONFIG_DIR/config.yaml"
MANIFEST="$DEPLOY_BASE/deployment_manifest.json"
CURRENT_LINK="$DEPLOY_BASE/current"
DEPLOYED_AT="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
DEPLOYMENT_ID="$ENV_NAME-$VERSION-${COMMIT:0:12}"

if [[ -e "$RELEASE_DIR" && "$FORCE" -ne 1 ]]; then
  echo "❌ Release directory already exists: $RELEASE_DIR"
  echo "   Use --force to replace it."
  exit 1
fi

if [[ -e "$RELEASE_DIR" ]]; then
  rm -rf "$RELEASE_DIR"
fi

mkdir -p "$RELEASE_DIR" "$CONFIG_DIR" "$OUTPUT_DIR" "$DEPLOY_BASE/logs"
git archive "$VERSION" | tar -x -C "$RELEASE_DIR"
cp "$CONFIG_SRC" "$CONFIG_DEST"
chmod 600 "$CONFIG_DEST"

echo "🐍 Creating release virtualenv..."
python3 -m venv "$RELEASE_DIR/.venv"
"$RELEASE_DIR/.venv/bin/python" -m pip install --upgrade pip >/dev/null
"$RELEASE_DIR/.venv/bin/python" -m pip install -e "$RELEASE_DIR[browser]" >/dev/null

PREVIOUS_VERSION=""
if [[ -L "$CURRENT_LINK" && -f "$MANIFEST" ]]; then
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

python3 - "$MANIFEST" "$RELEASE_DIR/deployment_manifest.json" <<PY
import json, os, sys
manifest = {
    "status": "active",
    "environment": "$ENV_NAME",
    "domain": "$DOMAIN",
    "version": "$VERSION",
    "git_tag": "$VERSION",
    "commit": "$COMMIT",
    "deployment_id": "$DEPLOYMENT_ID",
    "deployed_at": "$DEPLOYED_AT",
    "previous_version": "$PREVIOUS_VERSION",
    "paths": {
        "deploy_base": "$DEPLOY_BASE",
        "release_dir": "$RELEASE_DIR",
        "current": "$CURRENT_LINK",
        "config": "$CONFIG_DEST",
        "output_dir": "$OUTPUT_DIR",
        "logs": "$DEPLOY_BASE/logs"
    }
}
for path in sys.argv[1:]:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
PY

ln -sfn "$RELEASE_DIR" "$CURRENT_LINK"

echo "✅ Deployment active"
echo "   env:        $ENV_NAME"
echo "   version:    $VERSION"
echo "   commit:     $COMMIT"
echo "   current:    $CURRENT_LINK -> $RELEASE_DIR"
echo "   manifest:   $MANIFEST"
echo ""
echo "Run:"
echo "   scripts/run_deployed_daily.sh --root \"$DEPLOY_ROOT\" --env \"$ENV_NAME\" --domain \"$DOMAIN\" --date YYYY-MM-DD"
