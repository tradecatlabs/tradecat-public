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
python3 scripts/project/scripts/request.py event_stream --format json --limit 5
```

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
| `status --json` | `tradecat.status.v1` |
| `doctor --json` | `tradecat.doctor.v1` |
| `path <dataset> --json` | `tradecat.path_map.v1` |
| `datasets --json` | `tradecat.dataset_list.v1` |
| `sync <dataset> --json` | `tradecat.sync_result.v1` |
| `sync-all --json` | `tradecat.sync_results.v1` |
| `probe --json --no-write` | `tradecat.probe_results.v1` |
| `prune --json` | `tradecat.prune_result.v1` |
| `config show --json` | `tradecat.config.v1` |
| `export <dataset> --format json` | `tradecat.dataset_view.v1` |
| `doctor --bundle -` | `tradecat.support_bundle.v1` |
| `request.py <dataset> --format json` | `tradecat.request_result.v1` |

Breaking JSON changes require updating `agents/manifest.json`, this document,
and `scripts/project/tests/test_json_contract.py` in the same change.

## Exit Code Contract

- `0`: command succeeded or returned a valid readonly status payload.
- `1`: runtime, network, or business failure; JSON payload has `ok=false` when
  the command supports JSON.
- `2`: validation or argument failure; JSON payload has a stable `error` object
  when the command supports JSON.

Non-interactive commands must not return `0` with `ok=false`.

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

`scripts/project/scripts/start.sh start` returning `0` means watcher spawn or
already-running state, not proof that remote data is healthy. Follow it with
`status --json`, `doctor --json`, or `probe --json --no-write` when health is the
actual question.
