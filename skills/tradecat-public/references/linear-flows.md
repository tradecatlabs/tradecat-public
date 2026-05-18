# Linear Flows

## Flow 1: Public Sheet Signals

```text
scripts/request.py signal_flow/anomaly_panel
-> tradecat_sources.registry
-> tradecat_sources.sheets
-> tradecat.request_result.v1
-> Agent research loop input
```

No cache browser, TUI, installer, or local database is involved.

## Flow 2: Observe-only Research Cycle

```text
public sheet signal
-> Agent selects symbols and requested public Binance data
-> Agent calls public/read-only tools
-> agent_research_cycle.v1
-> agent_market_context.v1
-> context-audit
-> report only
```

Observe-only mode must not write paper ledger or open positions.

## Flow 3: Paper Execution

```text
agent_market_context.v1 + agent_trade_thesis.v1
-> context-audit ok
-> run-context / run-loop
-> explicit Agent sizing/leverage/exits
-> risk_decision
-> paper_execution
-> paper_ledger
-> cycles.jsonl + audit journal
```

Missing sizing or exits remains a deterministic reject.

## Flow 4: Position Management

```text
paper-report / paper_account_state
-> Agent position_management_thesis.v1
-> position-manage
-> hold / close / adjust_exit / reject
-> audit evidence
```

Default action is no change. Agent must explicitly authorize every paper position modification.

## Flow 5: Runtime Operations

```text
ops-check
-> start-auto-paper start
-> status / heal / stop
-> health-report / daily-report / alert-payload
-> web monitor
```

All writes are local `.runtime/auto-paper/` state. No real exchange execution exists in this repo.

## Flow 6: Validation

```text
validate-skill --strict
-> agent-smoke
-> verify
-> security-scan
-> supply-chain-audit
-> git diff --check
```
