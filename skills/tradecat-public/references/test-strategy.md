# Test Strategy

TradeCat Public is a headless Agent paper-trading runtime with an embedded Skill package. Tests protect three boundaries: public signal ingestion, Agent market-context contracts, and local paper/watch execution.

## Core Test Areas

| Area | Risk | Examples |
| --- | --- | --- |
| Skill/manifest governance | Agent gets stale or unsafe commands | `tests/test_agent_contract.py` |
| Public sheet request contract | Wrong tap, partial rows, missing provenance | `tests/test_transport.py`, `tests/test_dataset_consumption_contract.py` |
| Agent market context audit | Signed/private/account data enters pipeline | `tests/test_agent_market_context.py` |
| Thesis sizing/exits | TradeCat invents defaults or swallows missing inputs | `tests/test_pipeline.py`, `tests/test_service.py` |
| Paper ledger | Duplicate positions, bad mark-to-market, missing exits | `tests/test_paper_ledger.py`, `tests/test_paper_broker.py` |
| Runtime reports | Health/daily/replay/audit evidence drifts | `tests/test_replay_reporting.py`, `tests/test_audit_journal.py`, `tests/test_production_control.py` |
| Repository governance | Collaboration files, CI gates, and local runtime boundaries drift | `tests/test_public_repo_guardrails.py` |
| Safety scans | Credentials or private executor code leaks | `scripts/security-scan.sh`, `scripts/supply-chain-audit.sh` |

## Required Local Gate

```bash
bash scripts/agent-smoke.sh
bash scripts/verify.sh
bash scripts/validate-skill.sh --strict
bash scripts/security-scan.sh
bash scripts/supply-chain-audit.sh
python3 scripts/validate_dependency_policy.py
ruff format --check src tests scripts
git diff --check
```

## Regression Checklist

- `src/tradecat_terminal/`, root installers, and old watchdog scripts stay absent.
- `scripts/request.py` can list datasets and fetch `signal_flow` / `anomaly_panel`.
- `context-audit` rejects signed requests, key-like fields, account/order endpoints, and true safety flags.
- Missing Agent sizing/exits remains fail-closed.
- Explicit Agent sizing/exits can open paper positions.
- Same-symbol concurrency remains single-position by default and requires explicit Agent authorization to expand.
- Reports retain `schema_version=1.0.0`, error codes, provenance, and safety fields.
- Runtime files remain under ignored `.runtime/`.

## Performance Notes

The hot path is cyclic signal ingestion and paper runtime reporting. Keep sheet reads bounded, deduplicate repeated snapshot/event inputs, avoid unbounded Agent context payloads, and prefer schema validation plus small JSON reports over large opaque logs. Any future high-frequency loop must add timing metrics and bounded retry/backoff before increasing poll rate.
