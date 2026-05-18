# Analysis Contract

TradeCat separates data semantics from analysis output:

- `dataset_consumption_contract.json` tells an Agent how to understand rows.
- `analysis_report.v1` turns the latest local cache into a bounded observation
  report.
- `feature_bundle.v1` normalizes the report into per-symbol fact bundles.

The analysis contract is intentionally not a trading strategy. It does not
produce buy/sell advice, position sizing, price targets, automated execution
instructions, or backtest claims.

## Machine Entry

Readonly CLI entry:

```bash
bash scripts/run-tradecat.sh analyze --json
```

Formal schema:

```text
project/contracts/tradecat-analysis-report.schema.json
```

Payload schema:

```text
tradecat.analysis_report.v1
```

If the local cache has no analyzable rows, the command returns non-zero with:

```text
error.code = empty_analysis_cache
```

Repair path:

```bash
bash scripts/run-tradecat.sh doctor --sync --timeout 10
```

## Inputs

`analysis_report.v1` reads only the latest local cache projections for:

- `signal_flow`
- `anomaly_panel`

It does not fetch public network data. If fresher data is required, the caller
must explicitly run `sync`, `sync-all`, or `doctor --sync` first.

## Output Shape

The report exposes:

- `generated_at`: report generation timestamp.
- `analysis_window`: requested window metadata; v1 uses `latest_cached` mode.
- `dataset_freshness`: per-dataset cache readiness, row count, fetched time,
  quality tier, and time grain.
- `observations`: deterministic summaries derived from cached rows.
- `candidate_symbols`: symbols explicitly observed in structured entity fields.
- `evidence`: row-level evidence backing observations and candidates.
- `risk_flags`: machine-readable caveats.
- `limitations`: human-readable boundaries.

Candidate symbols are observations, not recommendations. v1 only extracts them
from explicit entity-key fields in `signal_flow` and `anomaly_panel`; it does
not guess symbols from free text.

## Boundaries

- No investment advice.
- No strategy scoring.
- No backtest or evaluation metrics.
- No trade execution.
- No network fetch.
- No cache writes.

Feature facts use `tradecat.feature_bundle.v1`. Future strategy, signal,
scoring, or evaluation layers must introduce their own schemas instead of
overloading `tradecat.analysis_report.v1`.

## Change Rule

Changing analysis output requires updating, in the same change:

- `agents/manifest.json`
- `references/agent-contract.md`
- this document
- `project/contracts/tradecat-analysis-report.schema.json`
- `project/tests/test_analysis_report.py`
- `project/tests/test_payload_schema_validation.py`
- `project/tests/test_agent_contract.py`
