# Agent Contract

This repository is a multi-Agent Skill wrapper around the TradeCat public
CLI/TUI project in `project/`. The canonical machine-readable contract
is `agents/manifest.json`; platform files such as `agents/openai.yaml` and
`agents/hermes.yaml` are thin adapters and must not become second sources of
truth.

Human + Hermes operating guide: `references/hermes-agent-guide.md`. Use it when the task is about local Hermes skill installation, development-vs-production boundaries, or Agent-supplied Binance market context.

## Hermes Skill Consumption

When this repo is installed under `~/.hermes/skills/tradecat-public`, Hermes should load `SKILL.md` first and then treat this file plus `agents/manifest.json` as the operating contract. The default working directory is always the skill root (`.`), not `project/`; use the root wrapper `bash scripts/run-tradecat.sh ...` unless a command explicitly says to enter `project/`.

Development is currently performed in `/home/lenovo/.projects/cat/tradecat-public`. Production use should consume a verified copy/clone/symlink under `~/.hermes/skills/tradecat-public`; do not mix local runtime files from development with production runtime state.

## Agent Fast Path

Use this order for inspection and diagnosis:

```bash
python3 -m json.tool agents/manifest.json >/dev/null
bash scripts/run-tradecat.sh status --json
bash scripts/run-tradecat.sh datasets --json
bash scripts/run-tradecat.sh path event_stream --json
bash scripts/run-tradecat.sh analyze --json
bash scripts/run-tradecat.sh features --json
python3 project/scripts/request.py event_stream --format json --limit 5
```

`datasets --json` includes each dataset's `consumption_contract`. For full
field semantics, missing-value rules, time grain, and quality tier, read
`project/src/tradecat_terminal/dataset_consumption_contract.json` or
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
| `network_readonly` | Reads public network data without writing cache. | `project/scripts/request.py event_stream --format json` |
| `local_cache_write` | Writes only local TradeCat cache, settings, or diagnostics. | `init`, `sync`, `doctor --repair`, `prune --apply` |
| `background_long_running` | Starts or supervises a local watcher. | `project/scripts/start.sh start`, `watch` |
| `paper_runtime_write` | Writes only local paper/watch runtime state, ledger, archive, PID, or logs; never real orders. | `auto run-loop --once`, `start-auto-paper.sh start` |
| `install_or_uninstall` | Changes user install paths, launchers, venv, or PATH guidance. | `install.sh`, `install.ps1`, `uninstall.*` |
| `security_or_supply_chain` | Runs scanner/audit tooling that may download metadata. | `security-scan.sh`, `supply-chain-audit.sh` |

Default Agent behavior must start with `local_readonly`. Do not run install,
uninstall, `prune --apply`, `sync`, paper runtime writes, or background watchers unless the task explicitly
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

Formal schema files live in `project/contracts/`. The command-level
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
`project/tests/test_payload_schema_validation.py`. It validates live
CLI/request JSON output and golden samples from
`project/tests/fixtures/json_contract/` against the formal schemas.
`jsonschema` is a dev/test dependency only; TradeCat runtime commands do not
depend on it.

Breaking JSON changes require updating `agents/manifest.json`, this document,
`project/tests/test_json_contract.py`,
`project/tests/test_agent_contract.py`, and
`project/tests/test_payload_schema_validation.py` in the same change.

## Agent-supplied Market Context Contract

Hermes/Agent may gather Binance public market context outside TradeCat, then hand a local JSON file to TradeCat for schema validation, signal alignment, paper/watch analysis, ledger/replay, and audit. TradeCat must not read Binance credentials, sign requests, read account state, or place real orders.

Canonical input schema:

- Payload schema: `tradecat_auto.agent_market_context.v1`.
- Schema file: `project/contracts/tradecat-auto-agent-market-context.schema.json`.
- Source/provenance manifest: `project/resources/agent_market_context/binance/provenance.manifest.json`.
- Audit command: `bash scripts/run-tradecat.sh auto context-audit --input <context.json> --json`.
- Paper/watch command: `bash scripts/run-tradecat.sh auto run-context --input <context.json> --mode paper --agent-margin-usdt <agent_decision> --paper-leverage <agent_decision> --json`.
- Replay command: `bash scripts/run-tradecat.sh auto replay-report --archive-path .runtime/cycles.jsonl --ledger-path .runtime/paper_ledger.json --json`.

Required command order:

1. Validate JSON syntax and schema/version.
2. Run `context-audit`.
3. Continue to `run-context` only when audit `ok=true` and Agent sizing is explicit. TradeCat defaults to no paper margin budget/cap, no fixed order size, and no leverage/notional upper cap; `--paper-margin-budget-usdt` is optional only for an operator-supplied extra paper cap. Paper exits are also intent-driven: no fixed stop-loss, take-profit, or time-stop is applied unless the Agent thesis supplies it.
4. Inspect `run_once_report.v1` / paper ledger / replay report; never convert paper output into real orders.

Allowed context families are intentionally narrow and public/read-only: `klines`, `order_book_depth`, `book_ticker`, `24h_ticker`, `funding_rate`, `premium_index`, `open_interest`, `open_interest_history`, `long_short_ratios`, and `taker_buy_sell_volume`. Each item must be `method=GET`, `requires_signature=false`, and `signed=false`.

Forbidden material includes API keys, secrets, signatures, listen keys, private keys, account/balance/position endpoints, order endpoints, leverage or margin mutation endpoints, and any instruction to execute real orders. `context-audit` must reject such input before `run-context`.

Automation payload schemas currently advertised through `agents/manifest.json` include:

| Command | Schema |
| --- | --- |
| `auto paper-report --json` | `tradecat_auto.paper_report.v1` |
| `auto market-universe --json` | `tradecat_auto.market_universe.v1` |
| `auto probe-public --json` | `tradecat_auto.public_probe.v1` |
| `auto run-once --mode paper --json` | `tradecat_auto.run_once_report.v1` |
| `auto run-loop --mode paper --once --json` | `tradecat_auto.service_cycle.v1` |
| `start-auto-paper.sh status/start/stop --json` | `tradecat_auto.paper_service_status.v1` |
| `auto context-audit --input <context.json> --json` | `tradecat_auto.agent_market_context_audit.v1` |
| `auto run-context --input <context.json> --mode paper --json` | `tradecat_auto.run_once_report.v1` |
| `auto replay-report --archive-path ... --ledger-path ... --json` | `tradecat_auto.replay_report.v1` |
| `auto audit-journal --json` | `tradecat_auto.audit_journal_summary.v1` |
| service-cycle audit write | `tradecat_auto.audit_journal_write.v1` |
| `auto health-report --json` | `tradecat_auto.production_health.v1` |
| `auto daily-report --json` | `tradecat_auto.daily_paper_report.v1` |
| `auto alert-payload --kind daily --json` | `tradecat_auto.telegram_alerts.v1` |

## Production Paper Runtime Reports

The production paper/watch runtime is local state only. Default paths live under
`project/.runtime/auto-paper/`: `service_state.json`, `paper_ledger.json`,
`cycles.jsonl`, `paper_audit.sqlite3`, and `paper-run-loop.log`. These files are
ignored by Git and must not be committed. Agents should treat them as
operator-local runtime evidence, not source assets.

Use `bash project/scripts/start-auto-paper.sh status --json` to inspect
whether the continuous paper loop is running. Use `auto health-report --json` for
heartbeat, ledger, archive, and audit-journal health; `auto daily-report --json`
for a daily paper/watch ledger summary; `auto audit-journal --json` for SQLite
checksum-chain status; and `auto alert-payload --kind daily --json` to format a
plain-text notification payload. All four report paths are local read-only and
retain the same safety boundary: no Binance API key, no signed request, no
account/order endpoint, and no real order. `audit_journal_write.v1` is the only
new local-write contract here; it writes paper/watch evidence into the local
SQLite journal and has no exchange side effect.

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
invalid `--window` or `--limit` arguments. Agent market-context failures use
`agent_market_context_load_failed` when the context file cannot be read/parsed,
`invalid_schema` or `invalid_schema_version` for envelope mismatch,
`credential_material_forbidden` for credential-like fields,
`signed_request_forbidden` for signed or signature-required items,
`forbidden_endpoint` / `endpoint_not_allowlisted` for account/order or unsupported endpoints,
and `unsupported_family` for market-data families outside the public/read-only allowlist.

## Remote Fetch Contract

There are two explicit remote paths:

1. Production path: `tradecat_terminal.sheets.fetch_csv_body`, used by installed
   CLI sync/probe and `project/scripts/validate_data_contract.py`.
   It uses `urllib3` retry/backoff/jitter and typed `RemoteCsvError`.
2. Zero-install fallback: `project/scripts/request.py`, kept standard
   library only so an Agent can execute it from raw GitHub without installing
   TradeCat. It shares `dataset_registry.json`, writes no local cache, and
   returns `tradecat.request_result.v1` for JSON requests.

The fallback path is intentional, not a hidden second source of truth. It may
have simpler transport behavior, but dataset/workbook/gid resolution must remain
derived from the same registry.

## Long-Running Semantics

`project/scripts/start.sh --json` is the machine-readable watcher
lifecycle control plane. The manifest advertises `status --json` as read-only
inspection, and `start --json` / `stop --json` / `watchdog.sh --json` as
mutating supervision commands. `restart --json` is operator-only: it is tested
and uses the same `tradecat.watch_status.v1` envelope, but it is intentionally
not a preferred Agent entrypoint.

`start` or `watchdog` returning `0` means watcher spawn or already-running
state, not proof that remote data is healthy. Follow it with `status --json`,
`doctor --json`, or `probe --json --no-write` when remote data health is the
actual question.
