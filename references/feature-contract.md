# Feature Contract

`tradecat.feature_bundle.v1` is the symbol-normalized fact layer.

It sits above `analysis_report.v1` and below any future signal, scoring,
backtest, or strategy contract. Its job is to answer:

```text
For this symbol, what facts can be verified from the local cache?
```

It does not answer:

```text
Should anyone buy, sell, hold, size, execute, or predict returns?
```

## Machine Entry

Readonly CLI entry:

```bash
bash scripts/run-tradecat.sh features --json
```

Formal schema:

```text
scripts/project/contracts/tradecat-feature-bundle.schema.json
```

Payload schema:

```text
tradecat.feature_bundle.v1
```

If no symbol can be normalized into feature facts, the command returns non-zero
with:

```text
error.code = empty_feature_cache
```

Repair path:

```bash
bash scripts/run-tradecat.sh doctor --sync --timeout 10
```

## Inputs

`feature_bundle.v1` reuses `analysis_report.v1` candidates and evidence. The
current input datasets are therefore:

- `event_stream`
- `anomaly_panel`
- `market_stats`

The first version gets symbol identity from explicit entity-key fields in
`anomaly_panel`. It does not infer symbols from free text.

## Output Shape

Top-level fields:

- `generated_at`
- `feature_window`
- `dataset_freshness`
- `symbols`
- `evidence`
- `risk_flags`
- `limitations`

Each `symbols[]` item includes:

- `symbol`
- `features[]`
- `source_dataset_keys`
- `freshness`
- `evidence_ids`
- `confidence`
- `risk_flags`
- `limitations`

Each `features[]` item includes:

- `name`
- `kind`
- `value`
- `value_type`
- `source_dataset_keys`
- `evidence_ids`
- `confidence`
- `description`

## Boundaries

- No investment advice.
- No signal score.
- No ranking beyond stable output order.
- No backtest or evaluation metrics.
- No return prediction.
- No trade execution.
- No network fetch.
- No cache writes.

Future signal, scoring, evaluation, or strategy layers must introduce separate
schemas and must not overload `tradecat.feature_bundle.v1`.

## Change Rule

Changing feature output requires updating, in the same change:

- `agents/manifest.json`
- `README.md` and `SKILL.md`
- `references/agent-contract.md`
- `references/linear-flows.md`
- root/project `AGENTS.md`
- this document
- `scripts/project/contracts/tradecat-feature-bundle.schema.json`
- `scripts/project/tests/test_feature_bundle.py`
- `scripts/project/tests/test_payload_schema_validation.py`
- `scripts/project/tests/test_agent_contract.py`
