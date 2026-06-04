# cluster - story grouping stage boundary

## Purpose

`stratum/stages/cluster` groups normalized articles into stable story clusters
for editing, monitoring, and downstream synthesis.

The package entrypoint `stratum.stages.cluster` is the stable import surface
for clustering helpers and confidence scoring.

## Modules

| File | Role |
|:---|:---|
| `__init__.py` | stable package surface for cluster helpers |
| `cluster.py` | stage CLI and cluster artifact assembly |
| `story_clusterer.py` | clustering, bridge split, and confidence algorithms |

## Boundaries

### Owns

- Turn normalized article records into `clusters.json`.
- Keep cluster object assembly separate from clustering policy/scoring logic.

### Does Not Own

- Does not extract entities or terms from raw evidence.
- Does not decide editorial block structure.
