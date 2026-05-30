#!/usr/bin/env bash
# Run daily pipeline from an active deployment, never from the dev worktree.

set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  scripts/run_deployed_daily.sh --root DEPLOY_ROOT --env production --domain storage --date YYYY-MM-DD [pipeline args...]
USAGE
}

DEPLOY_ROOT=""
ENV_NAME=""
DOMAIN=""
RUN_DATE=""
PIPELINE_ARGS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --root) DEPLOY_ROOT="${2:-}"; shift 2 ;;
    --env) ENV_NAME="${2:-}"; shift 2 ;;
    --domain) DOMAIN="${2:-}"; shift 2 ;;
    --date) RUN_DATE="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) PIPELINE_ARGS+=("$1"); shift ;;
  esac
done

if [[ -z "$DEPLOY_ROOT" || -z "$ENV_NAME" || -z "$DOMAIN" || -z "$RUN_DATE" ]]; then
  usage
  exit 2
fi

DEPLOY_BASE="$DEPLOY_ROOT/$ENV_NAME"
MANIFEST="$DEPLOY_BASE/deployment_manifest.json"
CURRENT="$DEPLOY_BASE/current"

if [[ ! -f "$MANIFEST" || ! -L "$CURRENT" ]]; then
  echo "❌ No active deployment at $DEPLOY_BASE"
  exit 1
fi

VALUES_FILE="$(mktemp)"
python3 - "$MANIFEST" > "$VALUES_FILE" <<'PY'
import json, sys
with open(sys.argv[1]) as f:
    m = json.load(f)
p = m["paths"]
print(m["version"])
print(m["commit"])
print(m["deployment_id"])
print(p["config"])
print(p["output_dir"])
print(p["logs"])
PY
VALUES=()
while IFS= read -r line; do
  VALUES+=("$line")
done < "$VALUES_FILE"
rm -f "$VALUES_FILE"

VERSION="${VALUES[0]}"
COMMIT="${VALUES[1]}"
DEPLOYMENT_ID="${VALUES[2]}"
CONFIG_PATH="${VALUES[3]}"
OUTPUT_DIR="${VALUES[4]}"
LOG_DIR="${VALUES[5]}"
PYTHON="$CURRENT/.venv/bin/python"

if [[ ! -x "$PYTHON" ]]; then
  echo "❌ Deployment Python not found: $PYTHON"
  exit 1
fi

mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/daily-${DOMAIN}-${RUN_DATE}.log"

export STRATUM_RUNTIME_MODE="deployment"
export STRATUM_RELEASE_VERSION="$VERSION"
export STRATUM_RELEASE_TAG="$VERSION"
export STRATUM_RELEASE_COMMIT="$COMMIT"
export STRATUM_DEPLOYMENT_ID="$DEPLOYMENT_ID"
export STRATUM_DEPLOYMENT_ENV="$ENV_NAME"
export STRATUM_DEPLOYMENT_MANIFEST="$MANIFEST"

echo "▶️  Running deployed daily"
echo "   env:     $ENV_NAME"
echo "   version: $VERSION"
echo "   commit:  $COMMIT"
echo "   log:     $LOG_FILE"

"$PYTHON" "$CURRENT/stratum/orchestrator/pipeline.py" \
  --domain "$DOMAIN" \
  --date "$RUN_DATE" \
  --config "$CONFIG_PATH" \
  --output-dir "$OUTPUT_DIR" \
  "${PIPELINE_ARGS[@]}" 2>&1 | tee "$LOG_FILE"
