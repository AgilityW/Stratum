#!/usr/bin/env bash
# Validate an active Stratum deployment without running external APIs.

set -euo pipefail

usage() {
  echo "Usage: $0 --root DEPLOY_ROOT --env production"
}

DEPLOY_ROOT=""
ENV_NAME=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --root) DEPLOY_ROOT="${2:-}"; shift 2 ;;
    --env) ENV_NAME="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "❌ Unknown argument: $1"; usage; exit 2 ;;
  esac
done

if [[ -z "$DEPLOY_ROOT" || -z "$ENV_NAME" ]]; then
  usage
  exit 2
fi

DEPLOY_BASE="$DEPLOY_ROOT/$ENV_NAME"
MANIFEST="$DEPLOY_BASE/deployment_manifest.json"
CURRENT="$DEPLOY_BASE/current"

if [[ ! -f "$MANIFEST" ]]; then
  echo "❌ Missing deployment manifest: $MANIFEST"
  exit 1
fi

if [[ ! -L "$CURRENT" ]]; then
  echo "❌ Missing current symlink: $CURRENT"
  exit 1
fi

python3 - "$MANIFEST" "$CURRENT" <<'PY'
import json, os, pathlib, subprocess, sys
manifest_path, current = sys.argv[1], sys.argv[2]
with open(manifest_path) as f:
    manifest = json.load(f)
paths = manifest["paths"]
errors = []
if manifest.get("status") != "active":
    errors.append("manifest status is not active")
if not manifest.get("version") or manifest.get("version") == "development":
    errors.append("deployment version is not locked")
if not manifest.get("commit"):
    errors.append("deployment commit is missing")
if pathlib.Path(current).resolve() != pathlib.Path(paths["release_dir"]).resolve():
    errors.append("current symlink does not point to manifest release_dir")
for key in ("config", "output_dir", "logs"):
    if not os.path.exists(paths[key]):
        errors.append(f"missing path: {key}={paths[key]}")
python = os.path.join(current, ".venv", "bin", "python")
if not os.path.exists(python):
    errors.append(f"missing deployment python: {python}")
else:
    result = subprocess.run(
        [python, "-c", "import stratum; print(stratum.__name__)"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        errors.append("deployment python cannot import stratum")
if os.path.exists(python):
    result = subprocess.run(
        [python, "-c", "import sys, yaml; yaml.safe_load(open(sys.argv[1]))", paths["config"]],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        errors.append(f"config is not valid YAML: {result.stderr.strip()}")
if errors:
    for error in errors:
        print(f"❌ {error}")
    sys.exit(1)
print("✅ deployment health ok")
print(f"   env:     {manifest['environment']}")
print(f"   version: {manifest['version']}")
print(f"   commit:  {manifest['commit']}")
PY
