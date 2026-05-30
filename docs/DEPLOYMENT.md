# Deployment

Stratum has two separate operating modes:

- Development: run from the working tree with `make daily` while code, prompts,
  templates, and tests are changing.
- Deployment: run only from a Git tag copied into an isolated release
  directory. Production must never run directly from `main` or a dirty working
  tree.

## Directory Model

Deployment uses this layout:

```text
{deploy_root}/{environment}/
  current -> releases/{version}
  deployment_manifest.json
  config/config.yaml
  logs/
  releases/
    v0.7.0/
      stratum/
      domains/
      scripts/
      .venv/
      deployment_manifest.json
```

`config.yaml` remains instance-owned and is copied into the deployment
environment. Secrets and local paths are not committed to Git.

## Release

Create a release from a clean development tree:

```bash
make release VERSION=v0.7.0
git push origin main --tags
```

`scripts/release.sh` refuses dirty worktrees, runs the full test suite, and
creates an annotated Git tag. The tag is the only deployable version handle.

## Deploy

Deploy a locked tag:

```bash
make deploy \
  VERSION=v0.7.0 \
  ENV=production \
  DOMAIN=storage \
  DEPLOY_ROOT="$HOME/WorkSpace/Stratum/deployments" \
  DEPLOY_CONFIG=/secure/stratum/config.yaml \
  OUTPUT_DIR="$HOME/WorkSpace/Stratum/Reports"
```

`scripts/deploy.sh` rejects branches and bare commits. It verifies that the
version is an existing Git tag, exports that tag with `git archive`, creates a
release-local virtualenv, copies the instance config, writes
`deployment_manifest.json`, and atomically moves `current` to the new release.

## Run

Production daily runs must use the deployed wrapper:

```bash
make run-deployed-daily \
  ENV=production \
  DOMAIN=storage \
  DATE=2026-05-30 \
  DEPLOY_ROOT="$HOME/WorkSpace/Stratum/deployments"
```

The wrapper exports:

- `STRATUM_RUNTIME_MODE=deployment`
- `STRATUM_RELEASE_VERSION`
- `STRATUM_RELEASE_COMMIT`
- `STRATUM_DEPLOYMENT_ID`
- `STRATUM_DEPLOYMENT_ENV`
- `STRATUM_DEPLOYMENT_MANIFEST`

The pipeline writes these values into each `run_manifest.json`, so every report
can be traced back to the deployed version and commit.

## Production Delivery

The Hermes production cron entrypoint must perform both delivery actions after a
successful deployed daily run:

- send the generated PDF from `paths.briefing_pdf` to the configured delivery
  channel
- copy the generated Markdown from `paths.briefing_md` into the Obsidian daily
  briefing folder:
  `/Users/ronnie/ObsidianSpace/RonnieVault/Wiki/DailyBrief/Storage`

The Markdown archive step is part of the production cron wrapper, not the core
pipeline. This keeps development and tests on local outputs while production
adds the delivery-specific copy after the deployed run succeeds.

## Health Check

```bash
make deploy-health ENV=production DEPLOY_ROOT="$HOME/WorkSpace/Stratum/deployments"
```

The health check verifies the active manifest, `current` symlink, config file,
output/log directories, deployment Python, and importability of `stratum`.

## Rollback

Rollback moves `current` back to a release that already exists under the
environment's `releases/` directory:

```bash
make rollback \
  VERSION=v0.6.3 \
  ENV=production \
  DEPLOY_ROOT="$HOME/WorkSpace/Stratum/deployments"
```

Rollback does not rebuild code. It only reactivates a previously deployed,
tag-locked release and updates the environment manifest.

## Invariants

- Development runs may use the working tree and are marked `mode=development`.
- Deployment runs must use `scripts/run_deployed_daily.sh` and are marked
  `mode=deployment`.
- Deployment requires a Git tag, not a branch name and not a bare commit.
- Each deployed report manifest records version, commit, deployment id, config
  path, output root, and stage statuses.
- Releasing requires a clean worktree and passing tests.
- Rollback is redeploying a previous local release by tag.
