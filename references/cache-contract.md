# Cache Contract

The runtime data source for CLI and TUI is the local JSON cache under `TRADECAT_CACHE_DIR`; when unset, the bundled project defaults to `scripts/project/.tradecat/cache`.

## Required Files

Each dataset cache directory must keep:

```text
datasets/<dataset_key>/
|-- manifest.json
|-- latest.json
|-- latest.jsonl
|-- latest.csv
`-- snapshots/
```

`event_stream` also keeps:

```text
datasets/event_stream/stream_events.json
```

## Snapshot Rules

- Snapshot datasets append a new snapshot only when the full CSV matrix hash changes.
- Historical snapshots are permanent by default.
- Prune is explicit and dry-run by default; deletion requires `tradecat prune --apply`.
- `TRADECAT_CACHE_COMPRESSION=gzip` only affects newly written snapshots.
- Dataset manifest, stream state, structured latest files, and root manifest
  writes must use same-directory atomic replacement.
- Runtime cache mutation must be protected by cross-platform `filelock` locks;
  lock timeout is controlled by `TRADECAT_LOCAL_STATE_LOCK_TIMEOUT`.

## Stream Rules

- `event_stream` merges incrementally by `event_key` and `normalized_event_key`.
- Repeated events update `seen_count` and `last_seen_at`.
- Structured latest files are generated from the merged stream state.

## Export Rules

- `tradecat export` reads only local cache and must not fetch remote CSV.
- `csv` and `jsonl` preserve raw fields.
- `table` preserves physical `A/B/C...` columns and raw header rows.

## Status Rules

- `tradecat status` reports aggregate dataset counts, cache byte size, and one
  row per dataset.
- Per-dataset `cache_state` is `ready` when `latest.json` exists, `initialized`
  when the dataset directory exists without latest files, and `missing` when no
  dataset cache directory exists.
- `tradecat doctor` returns non-zero only for local cache errors; unsynced active
  datasets are warnings so first-run users get actionable guidance.
- `tradecat doctor` includes `repair_hints`; `tradecat doctor --fix` may create
  local cache directories but must not trigger remote CSV sync.
- `tradecat doctor --sync` is the explicit network repair path; it may sync all
  active datasets and should fail non-zero when the requested remote sync fails.
- When all active datasets are unsynced, `tradecat doctor` must call this out as
  first-run empty cache and include both `tradecat sync-all` and weak-network
  timeout guidance.
- `tradecat doctor --repair` may migrate local cache metadata and preserve
  backups; it must not silently delete snapshots or fetch remote data.
- `tradecat doctor --verbose` includes settings health, migration status, recent
  typed errors, and cache disk-waterline diagnostics.
- `tradecat doctor --bundle [PATH]` writes a public-safe JSON support bundle; no
  credential values, cache row payloads, or private environment dumps are allowed.

## Migration Rules

- Current cache metadata schema version is `1`.
- Dataset manifests and `event_stream` state files must carry `schema_version`.
- Migrations are explicit, idempotent, and backed up under
  `migration_backups/<timestamp>/` before metadata is rewritten.
- Failed migration must restore backed-up metadata before surfacing the error.
- Future schema changes must add fixtures and doctor migration status coverage.

## Settings Rules

- Settings writes use lock + atomic replace.
- Existing settings are copied to `settings.json.bak` before successful writes.
- Corrupt settings are preserved as `settings.json.corrupt-*.bak` and surfaced by
  doctor instead of being silently treated as a healthy empty config.
