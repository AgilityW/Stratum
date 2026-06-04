"""Deployment/runtime identity helpers.

Development runs are allowed to use the working tree. Deployment runs are
identified by environment variables set by scripts/run_daily.sh and
must point at a locked Git tag + commit.
"""

from __future__ import annotations

import os
import subprocess
from datetime import datetime, timezone


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _git_output(args: list[str], cwd: str = PROJECT_ROOT) -> str:
    try:
        return subprocess.check_output(
            ["git", *args],
            cwd=cwd,
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except Exception:
        return ""


def current_commit(cwd: str = PROJECT_ROOT) -> str:
    return _git_output(["rev-parse", "HEAD"], cwd)


def current_tag(cwd: str = PROJECT_ROOT) -> str:
    return _git_output(["describe", "--tags", "--exact-match"], cwd)


def worktree_dirty(cwd: str = PROJECT_ROOT) -> bool:
    return bool(_git_output(["status", "--porcelain"], cwd))


def runtime_identity(env: dict | None = None, cwd: str = PROJECT_ROOT) -> dict:
    """Return a manifest-safe identity for the current runtime."""
    env = env or os.environ
    mode = env.get("STRATUM_RUNTIME_MODE") or "development"
    version = env.get("STRATUM_RELEASE_VERSION") or current_tag(cwd) or "development"
    commit = env.get("STRATUM_RELEASE_COMMIT") or current_commit(cwd)
    deployment_id = env.get("STRATUM_DEPLOYMENT_ID") or ""
    deployment_env = env.get("STRATUM_DEPLOYMENT_ENV") or ""
    manifest_path = env.get("STRATUM_DEPLOYMENT_MANIFEST") or ""
    identity = {
        "mode": mode,
        "version": version,
        "commit": commit,
        "git_tag": env.get("STRATUM_RELEASE_TAG") or (version if version != "development" else current_tag(cwd)),
        "worktree_dirty": worktree_dirty(cwd) if mode == "development" else False,
        "deployment_id": deployment_id,
        "deployment_env": deployment_env,
        "deployment_manifest": manifest_path,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    if mode == "deployment":
        identity["locked"] = bool(version and version != "development" and commit and deployment_id)
    else:
        identity["locked"] = False
    return identity
