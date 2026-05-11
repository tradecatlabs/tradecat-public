# Agent Contract

This repository is a multi-Agent Skill wrapper around the TradeCat public
CLI/TUI project in `scripts/project/`. The canonical machine-readable contract
is `agents/manifest.json`; platform files such as `agents/openai.yaml` and
`agents/hermes.yaml` are thin adapters and must not become second sources of
truth.

## Agent Fast Path

Use this order for inspection and diagnosis:

```bash
python3 -m json.tool agents/manifest.json >/dev/null
bash scripts/run-tradecat.sh status --json
bash scripts/run-tradecat.sh datasets --json
bash scripts/run-tradecat.sh path event_stream --json
bash scripts/run-tradecat.sh analyze --json
bash scripts/run-tradecat.sh features --json
python3 scripts/project/scripts/request.py event_stream --format json --limit 5
```

`datasets --json` includes each dataset's `consumption_contract`. For full
field semantics, missing-value rules, time grain, and quality tier, read
`scripts/project/src/tradecat_terminal/dataset_consumption_contract.json` or
`references/dataset-consumption-contract.md`.

`analyze --json` reads only local cache and returns
`tradecat.analysis_report.v1`. It is an observation report for Agents, not
investment advice, scoring, backtest, or automated trade execution. If it
returns `empty_analysis_cache`, explicitly warm the cache before retrying.

`features --json` reads only local cache through `analysis_report.v1` and
returns `tradecat.feature_bundle.v1`. It is a per-symbol fact bundle, not a
signal score, strategy, return forecast, or execution instruction. If it returns
`empty_feature_cache`, warm the cache and confirm `anomaly_panel` has entity-key
rows.

Only write local cache after the readonly path proves what is needed:

```bash
bash scripts/run-tradecat.sh sync event_stream --json --timeout 10
bash scripts/run-tradecat.sh doctor --json
```

Before delivery, run:

```bash
bash scripts/agent-smoke.sh
```

## Command Risk Classes

| Class | Meaning | Examples |
| --- | --- | --- |
| `local_readonly` | Reads tracked files, settings, or cache metadata only. | `status --json`, `datasets --json`, `path event_stream --json` |
| `network_readonly` | Reads public network data without writing cache. | `scripts/project/scripts/request.py event_stream --format json` |
| `local_cache_write` | Writes only local TradeCat cache, settings, or diagnostics. | `init`, `sync`, `doctor --repair`, `prune --apply` |
| `background_long_running` | Starts or supervises a local watcher. | `scripts/project/scripts/start.sh start`, `watch` |
| `install_or_uninstall` | Changes user install paths, launchers, venv, or PATH guidance. | `install.sh`, `install.ps1`, `uninstall.*` |
| `security_or_supply_chain` | Runs scanner/audit tooling that may download metadata. | `security-scan.sh`, `supply-chain-audit.sh` |

Default Agent behavior must start with `local_readonly`. Do not run install,
uninstall, `prune --apply`, or background watchers unless the task explicitly
requires that side effect.

## JSON Contract

All advertised JSON payloads use:

- `schema`: stable payload identity, for example `tradecat.status.v1`.
- `schema_version`: currently `1.0.0`.
- `ok`: boolean command result when applicable.
- `error`: object on failures, not a free-form string.

Stable error object:

```json
{
  "code": "invalid_dataset_key",
  "kind": "validation",
  "message": "human-readable summary",
  "hint": "actionable repair hint",
  "retryable": false
}
```

Known JSON schemas:

| Command | Schema |
| --- | --- |
| `init --json` | `tradecat.init.v1` |
| `status --json` | `tradecat.status.v1` |
| `doctor --json` | `tradecat.doctor.v1` |
| `path <dataset> --json` | `tradecat.path_map.v1` |
| `datasets --json` | `tradecat.dataset_list.v1` |
| `analyze --json` | `tradecat.analysis_report.v1` |
| `features --json` | `tradecat.feature_bundle.v1` |
| `sync <dataset> --json` | `tradecat.sync_result.v1` |
| `sync-all --json` | `tradecat.sync_results.v1` |
| `probe <dataset> --json --no-write` | `tradecat.probe_result.v1` |
| `probe --json --no-write` | `tradecat.probe_results.v1` |
| `prune --json` | `tradecat.prune_result.v1` |
| `config show --json` | `tradecat.config.v1` |
| `start.sh status/start/stop --json`; `watchdog.sh --json` | `tradecat.watch_status.v1` |
| `export <dataset> --format json` | `tradecat.dataset_view.v1` |
| `doctor --bundle -` | `tradecat.support_bundle.v1` |
| `request.py <dataset> --format json` | `tradecat.request_result.v1` |
| `request.py --datasets --format json` | `tradecat.request_dataset_list.v1` |

Formal schema files live in `scripts/project/contracts/`. The command-level
schemas intentionally pin the stable envelope and high-value fields for Agent
parsing without making every output closed-world brittle:

| Schema File | Pinned Payload |
| --- | --- |
| `tradecat-config.schema.json` | `tradecat.config.v1` |
| `tradecat-analysis-report.schema.json` | `tradecat.analysis_report.v1` |
| `tradecat-feature-bundle.schema.json` | `tradecat.feature_bundle.v1` |
| `tradecat-doctor.schema.json` | `tradecat.doctor.v1` |
| `tradecat-init.schema.json` | `tradecat.init.v1` |
| `tradecat-status.schema.json` | `tradecat.status.v1` |
| `tradecat-path-map.schema.json` | `tradecat.path_map.v1` |
| `tradecat-dataset-list.schema.json` | `tradecat.dataset_list.v1` |
| `tradecat-sync-result.schema.json` | `tradecat.sync_result.v1` |
| `tradecat-sync-results.schema.json` | `tradecat.sync_results.v1` |
| `tradecat-probe-result.schema.json` | `tradecat.probe_result.v1` |
| `tradecat-probe-results.schema.json` | `tradecat.probe_results.v1` |
| `tradecat-prune-result.schema.json` | `tradecat.prune_result.v1` |
| `tradecat-request-result.schema.json` | `tradecat.request_result.v1` |
| `tradecat-request-dataset-list.schema.json` | `tradecat.request_dataset_list.v1` |
| `tradecat-dataset-view.schema.json` | `tradecat.dataset_view.v1` |
| `tradecat-support-bundle.schema.json` | `tradecat.support_bundle.v1` |
| `tradecat-watch-status.schema.json` | `tradecat.watch_status.v1` |
| `tradecat-dataset-consumption-contract.schema.json` | `tradecat.dataset_consumption_contract.v1` |

Every schema advertised in `agents/manifest.json` must have one command-level
schema file. Non-command resource schemas, such as the dataset consumption
contract schema, are allowed only when a tracked resource is itself a machine
contract. `tradecat.watch_cycle.v1` is intentionally CLI-internal and is not part
of the formal Agent surface. Promoting it requires a future manifest entry,
schema table update, live payload validation, and bounded smoke coverage in the
same change.

Real payload validation lives in
`scripts/project/tests/test_payload_schema_validation.py`. It validates live
CLI/request JSON output and golden samples from
`scripts/project/tests/fixtures/json_contract/` against the formal schemas.
`jsonschema` is a dev/test dependency only; TradeCat runtime commands do not
depend on it.

Breaking JSON changes require updating `agents/manifest.json`, this document,
`scripts/project/tests/test_json_contract.py`,
`scripts/project/tests/test_agent_contract.py`, and
`scripts/project/tests/test_payload_schema_validation.py` in the same change.

## Exit Code Contract

- `0`: command succeeded or returned a valid readonly status payload.
- `1`: runtime, network, or business failure; JSON payload has `ok=false` when
  the command supports JSON.
- `2`: validation or argument failure; JSON payload has a stable `error` object
  when the command supports JSON.

Non-interactive commands must not return `0` with `ok=false`.

Dataset lookup failures use `error.code=invalid_dataset_key`. Local
configuration failures, such as an unsupported `TRADECAT_CACHE_COMPRESSION`, use
`error.code=invalid_runtime_configuration`; unexpected local failures use
`error.code=local_runtime_error`. Watcher status failures use
`error.code=watch_not_running` when no watcher process is running. Do not
collapse these into dataset errors. Analysis report failures use
`error.code=empty_analysis_cache` when local analysis inputs are missing and
`error.code=invalid_analysis_request` for invalid `--window` or `--limit`
arguments.
Feature bundle failures use `error.code=empty_feature_cache` when no symbol can
be normalized into feature facts and `error.code=invalid_feature_request` for
invalid `--window` or `--limit` arguments.

## Remote Fetch Contract

There are two explicit remote paths:

1. Production path: `tradecat_terminal.sheets.fetch_csv_body`, used by installed
   CLI sync/probe and `scripts/project/scripts/validate_data_contract.py`.
   It uses `urllib3` retry/backoff/jitter and typed `RemoteCsvError`.
2. Zero-install fallback: `scripts/project/scripts/request.py`, kept standard
   library only so an Agent can execute it from raw GitHub without installing
   TradeCat. It shares `dataset_registry.json`, writes no local cache, and
   returns `tradecat.request_result.v1` for JSON requests.

The fallback path is intentional, not a hidden second source of truth. It may
have simpler transport behavior, but dataset/workbook/gid resolution must remain
derived from the same registry.

## Long-Running Semantics

`scripts/project/scripts/start.sh --json` is the machine-readable watcher
lifecycle control plane. The manifest advertises `status --json` as read-only
inspection, and `start --json` / `stop --json` / `watchdog.sh --json` as
mutating supervision commands. `restart --json` is operator-only: it is tested
and uses the same `tradecat.watch_status.v1` envelope, but it is intentionally
not a preferred Agent entrypoint.

`start` or `watchdog` returning `0` means watcher spawn or already-running
state, not proof that remote data is healthy. Follow it with `status --json`,
`doctor --json`, or `probe --json --no-write` when remote data health is the
actual question.
