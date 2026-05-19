# Agent Contract

This repository is the TradeCat public Python project with an embedded Skill package in `skills/tradecat-public/`. The canonical machine-readable contract is `skills/tradecat-public/agents/manifest.json`; platform files are thin adapters and must not become second sources of truth.

## Agent Fast Path

```bash
python3 -m json.tool skills/tradecat-public/agents/manifest.json >/dev/null
python3 scripts/request.py --datasets --format json
python3 scripts/request.py signal_flow --format json --limit 5
python3 scripts/request.py anomaly_panel --format json --limit 0
bash scripts/run-tradecat.sh soft-layer --json
bash scripts/run-tradecat.sh paper-report --json
bash scripts/start-auto-paper.sh status --json
```

Only enter paper/watch when Agent-supplied context and thesis pass audit:

```bash
bash scripts/binance-public-bundle.sh --symbols BTCUSDT,ETHUSDT --json
bash scripts/run-tradecat.sh agent-market-context --symbol BTCUSDT --json
bash scripts/run-tradecat.sh context-audit --input context.json --json
bash scripts/run-tradecat.sh run-context --input context.json --mode paper --json
bash scripts/run-tradecat.sh strategy-review --ledger-path .runtime/auto-paper/paper_ledger.json --archive-path .runtime/auto-paper/cycles.jsonl --json
```

## Command Risk Classes

| Class | Meaning | Examples |
| --- | --- | --- |
| `local_readonly` | Reads tracked files or ignored runtime metadata only. | `soft-layer`, `paper-report`, `start-auto-paper.sh status` |
| `network_readonly` | Reads public network resources without credentials or signatures. | `scripts/request.py signal_flow`, `scripts/request.py anomaly_panel` |
| `paper_runtime_write` | Writes only local paper/watch runtime state under ignored `.runtime/`. | `run-context`, `run-loop --once`, `start-auto-paper.sh start` |
| `security_or_supply_chain` | Runs scanner/audit tooling. | `security-scan.sh`, `supply-chain-audit.sh` |

Default Agent behavior must start with `local_readonly` or `network_readonly`. Do not start paper runtime unless the task explicitly requires that local side effect.

## Stable JSON Envelope

Advertised payloads must include stable machine fields:

- `schema`
- `schema_version`
- `ok` when the command is a command result
- `error_code` or `error.code` on failures
- `provenance` when external data or Agent input is involved
- `safety` or explicit `real_orders=false`, `signed_requests=false`, `reads_api_keys=false` for trading-adjacent outputs

Stable error object:

```json
{
  "code": "agent_sizing_required",
  "kind": "risk_reject",
  "message": "Agent sizing is required for paper execution.",
  "hint": "Provide explicit paper_intent sizing/leverage/exits in agent_trade_thesis.",
  "retryable": false
}
```

## Public Signal Contract

Public sheet access is limited to `scripts/request.py` and `src/tradecat_sources/`.

- Dataset registry: `src/tradecat_sources/dataset_registry.json`
- Dataset consumption contract: `src/tradecat_sources/dataset_consumption_contract.json`
- Result schema: `contracts/tradecat-request-result.schema.json`
- Dataset-list schema: `contracts/tradecat-request-dataset-list.schema.json`

The canonical signal taps are `signal_flow` and `anomaly_panel`. `signal_flow` is event-like and should be deduplicated by event identity. `anomaly_panel` is snapshot-like and should be treated as current state across all榜单/tabs, not as a single first row.

## Agent-supplied Market Context

Hermes/Agent may gather Binance public market context outside TradeCat, then hand a local JSON file to TradeCat for validation and paper/watch. TradeCat must not read Binance credentials, sign requests, read account state, or place real orders.

Canonical schemas:

- `tradecat_auto.agent_research_cycle.v1`
- `tradecat_auto.agent_market_context.v1`
- `tradecat_auto.agent_trade_thesis.v1`
- `tradecat_auto.position_management_thesis.v1`
- `tradecat_auto.paper_autonomy_profile.v1`
- `tradecat_auto.portfolio_risk_policy.v1`
- `tradecat_auto.audited_intent_handoff.v1`

Allowed market-data families are public/read-only only: `klines`, `order_book_depth`, `book_ticker`, `24h_ticker`, `funding_rate`, `premium_index`, `open_interest`, `open_interest_history`, `long_short_ratios`, and `taker_buy_sell_volume`.

For broad candidate scans, prefer `bash scripts/binance-public-snapshot.sh --symbols BTCUSDT,ETHUSDT --json` before per-symbol bundles. It batches the Binance public endpoints that support no-symbol snapshots (`ticker_price`, `24h_ticker`, `book_ticker`, `premium_index`) and explicitly reports the remaining per-symbol families (`order_book_depth`, OI, funding history, long/short ratios, taker flow, klines).

Each market-data item must be `method=GET`, `requires_signature=false`, and `signed=false`. Forbidden material includes API keys, secrets, signatures, listen keys, private keys, account/balance/position endpoints, order endpoints, leverage or margin mutation endpoints, and any instruction to execute real orders.

## Paper Execution Rules

- Explicit CLI override has highest priority.
- `agent_trade_thesis.paper_intent` is accepted when it supplies sizing/leverage and exits.
- Missing sizing/leverage/exits must fail closed with structured reject.
- TradeCat must not invent default margin, notional, leverage, stop loss, take profit, or time stop.
- Local `paper_autonomy_profile.v1` may be auto-generated under ignored `.runtime/auto-paper/` for paper-only autonomy bootstrap; explicit `agent_trade_thesis.v1` still has priority, and `TRADECAT_AUTO_PAPER_AUTONOMY_ENABLED=0` restores strict external-thesis-only fail-closed behavior.
- Multiple open paper positions for the same symbol are allowed only when Agent thesis explicitly grants `allow_multiple_open_positions_per_symbol=true` or a positive `max_concurrent_positions_per_symbol`.
- `market-universe`, `market-snapshot`, and `probe-public` are diagnostics/research helpers, not the canonical Agent market-context input surface.

## Runtime Reports

Local paper/watch runtime defaults to `.runtime/auto-paper/` and is ignored by Git. Reports include:

- `paper-report`: `tradecat_auto.paper_report.v1`
- `audit-journal`: `tradecat_auto.audit_journal_summary.v1`
- `health-report`: `tradecat_auto.production_health.v1`
- `daily-report`: `tradecat_auto.daily_paper_report.v1`
- `alert-payload`: `tradecat_auto.telegram_alerts.v1`
- `replay-report`: `tradecat_auto.replay_report.v1`
- `strategy-review`: `tradecat_auto.strategy_review_report.v1`, optionally writes ignored `.runtime/auto-paper/strategy_state.json`

These commands read local paper evidence only; they never touch Binance private APIs.
