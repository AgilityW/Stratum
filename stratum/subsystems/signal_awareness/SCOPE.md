# Signal Awareness Scope

Signal Awareness is an independent deterministic subsystem that detects early
signal shifts from current evidence, historical snapshots, and optional signal
anchors. Its purpose is to sense rising themes early enough that the system can
prepare collection and query expansion before the signal becomes a fully
developed coverage spike. It is intentionally not integrated into the main
pipeline yet.

The package entrypoint `stratum.subsystems.signal_awareness` is the stable
import surface for detection, anchor normalization, topic normalization, and
preparation-plan assembly.

## Responsibilities

- Detect rising domain signals from current record batches and historical topic
  snapshots before downstream collection scope is widened.
- Support anchor-backed detection through a caller-provided registry of known
  event, conference, launch-window, or other signal anchors.
- Emit structured preparation plans that propose temporary source expansion,
  direct-fetch hubs, query injections, and daily-target changes.
- Emit machine-readable snapshots and diagnostics suitable for future DB
  persistence, dashboards, or orchestrator dry runs.
- Stay reusable outside the daily pipeline so callers can run it in notebooks,
  cron prototypes, or manual analysis loops.

## Non-Responsibilities

- Does not mutate `domain.yaml`, `queries.yaml`, source registries, or runtime
  manifests.
- Does not integrate itself into `stratum/orchestrator/pipeline.py`.
- Does not run watchlist, discovery, RSS, browser, direct fetch, or web search.
- Does not persist SQLite state directly. Callers own DB writes.
- Does not decide final report inclusion or render any report output.

## Inputs

| Input | Meaning |
|:---|:---|
| `records` | Current record batch, usually collector, watchlist, or observation-layer article-like records. |
| `topic_rules` | Caller-provided topic taxonomy used to bucket current evidence into comparable snapshot counts. |
| `historical_snapshots` | Prior snapshot records used to compute baseline means, standard deviations, and decay streaks. |
| `anchor_registry` | Optional signal anchors with aliases, date windows, query terms, temporary sources, and direct-fetch targets. |
| `active_signals` | Optional currently active signal-preparation state used to decide maintain vs archive actions. |

## Outputs

| Output File | Purpose |
|:---|:---|
| `signal_awareness.json` | Full detection payload including snapshot, topic signals, anchor signals, emergent clusters, and diagnostics. |
| `signal_plan.json` | Compact preparation plan with activate, maintain, archive, or observe decisions and proposed source/query/target changes. |

## Module Map

| Module | Scope |
|:---|:---|
| `topics.py` | Topic-rule normalization and per-record topic classification. |
| `anchors.py` | Conference-anchor normalization, alias matching, window-state evaluation, and confidence scoring. |
| `snapshots.py` | Snapshot creation, topic z-score comparison, and anchor decay streak logic. |
| `emergence.py` | Unanchored event-cluster detection for repeated event-like records not already explained by known anchors. |
| `planning.py` | Activation, maintain, observe, and archive preparation planning. |
| `runner.py` | Public orchestration API and JSON writer for the independent subsystem. |
| `contracts.py` | Stable output filenames and payload guards. |

## Design Rules

- Keep the subsystem pure. Detection and planning functions accept Python
  records and return JSON-friendly payloads.
- Keep integration concerns out of the subsystem. Future pipeline wiring must
  happen in `orchestrator/`, not inside this package.
- Treat anchor registries, topic taxonomies, and active state as caller-owned
  inputs. This subsystem consumes them but does not own their storage format.
- Prefer explicit, stable JSON outputs because the first production use should
  be dry-run inspection rather than hidden orchestration.
