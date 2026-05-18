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
contracts/tradecat-feature-bundle.schema.json
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

- `signal_flow`
- `anomaly_panel`

The first version gets symbol identity from explicit entity-key fields in
`signal_flow` and `anomaly_panel`. It does not infer symbols from free text.

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

- `skills/tradecat-public/agents/manifest.json`
- `README.md` and `skills/tradecat-public/SKILL.md`
- `skills/tradecat-public/references/agent-contract.md`
- `skills/tradecat-public/references/linear-flows.md`
- root `AGENTS.md`
- this document
- `contracts/tradecat-feature-bundle.schema.json`
- `tests/test_feature_bundle.py`
- `tests/test_payload_schema_validation.py`
- `tests/test_agent_contract.py`
