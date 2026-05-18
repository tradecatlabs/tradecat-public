# Dataset Consumption Contract

The machine-readable dataset consumption contract lives at:

```text
src/tradecat_sources/dataset_consumption_contract.json
```

It describes how Agents should interpret public online sheet data without relying on hidden server schemas.

## Current Signal Surfaces

- `signal_flow`: event-style signal feed. Consumers must deduplicate repeated local reads of the same upstream event.
- `anomaly_panel`: snapshot-style anomaly board. Consumers must read all榜单/tabs and all rows, then aggregate by symbol when needed.

## Contract Rules

- Treat sheet content as public signal input, not as a trading instruction.
- Preserve source provenance in downstream `agent_research_cycle.v1` and `agent_market_context.v1`.
- Do not infer paper sizing, leverage, stop loss, take profit, or time stop from sheet rows alone.
- Missing values remain missing. Agents may explain uncertainty, but TradeCat must not silently replace missing values with trading defaults.
- If upstream sheet fetch fails, emit structured request errors and do not convert the failure into an empty bullish/bearish signal.

## Validation

```bash
PYTHONPATH=src python3 scripts/validate_dataset_consumption_contract.py
PYTHONPATH=src python3 scripts/validate_data_contract.py
```
