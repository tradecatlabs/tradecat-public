# Dataset Consumption Contract

TradeCat now separates two registry layers:

- `dataset_registry.json`: where public data lives and how to fetch it.
- `dataset_consumption_contract.json`: how Agents should interpret the rows.

The consumption contract is intentionally about semantics, not strategy. It
describes field identity, missing values, time grain, quality tier, and minimum
column groups. The first readonly observation layer is
`tradecat.analysis_report.v1`; signal scoring, backtests, and trading decisions
still belong to separate future contracts.

## Machine Entry

Canonical file:

```text
scripts/project/src/tradecat_terminal/dataset_consumption_contract.json
```

Formal schema:

```text
scripts/project/contracts/tradecat-dataset-consumption-contract.schema.json
```

Validation:

```bash
cd scripts/project
PYTHONPATH=src python3 scripts/validate_dataset_consumption_contract.py
```

Agents can also read the same semantics from:

```bash
bash scripts/run-tradecat.sh datasets --json
```

Each dataset row includes `consumption_contract` with:

- `primary_entity`: what one row primarily represents.
- `time_grain`: snapshot, aggregate window, or event time semantics.
- `quality_tier`: source reliability class.
- `missing_value_policy`: how empty cells and missing columns are interpreted.
- `required_column_groups`: minimum column groups for stable consumption.
- `fields`: canonical names, source column aliases, role, type, nullability,
  unit, and description.

## Current Dataset Semantics

| Dataset | Primary Entity | Time Grain | Quality Tier |
| --- | --- | --- | --- |
| `market_snapshot` | `contract_symbol` | `latest_snapshot` | `public_sheet_best_effort` |
| `anomaly_panel` | `contract_symbol` | `latest_snapshot` | `public_sheet_best_effort` |
| `market_stats` | `market_window` | `aggregated_window` | `public_sheet_best_effort` |
| `event_stream` | `event` | `event_time` | `public_sheet_best_effort` |

## Missing Values

The current policy is `empty_string_is_missing`:

- Empty string and blank sheet cells mean missing.
- Missing required columns are contract errors.
- Numeric zero is an observed value, not missing.

Consumers must not infer that a blank value is bearish, bullish, zero, or
unchanged without a downstream analysis contract.

## Quality Boundary

`public_sheet_best_effort` means the data is suitable for inspection, research,
and Agent summaries. It is not a promise of market-data completeness, exchange
accuracy, or trading execution readiness.

## Change Rule

Changing dataset semantics requires updating, in the same change:

- `dataset_consumption_contract.json`
- `tradecat-dataset-consumption-contract.schema.json` when structure changes
- `scripts/validate_dataset_consumption_contract.py`
- tests covering `datasets --json` and payload schema validation
- this reference and `agents/manifest.json`
