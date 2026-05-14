# Test Strategy

This reference is the QA entrypoint for TradeCat public. It describes the
current product understanding, test scope, risk model, automation layers, and
release gate. It is intentionally executable-first: every item should map to a
local command, a CI job, or a concrete manual check.

## Product Understanding

TradeCat public is a Skill-wrapped Python CLI/TUI project. The root repository
is the Agent/Skill shell; the runnable user project is `scripts/project/`.

Core users:

- Terminal users installing `tradecat`, `tcat`, or `tradecat-terminal`.
- Agents such as Hermes/OpenAI consuming machine-readable contracts.
- Maintainers validating public release, installer, and data-contract safety.

Core flows:

```text
install -> init -> sync / doctor --sync -> status/path/datasets -> TUI/export
Agent -> agents/manifest.json -> status/datasets/path -> request fallback/sync
Agent -> analyze --json -> features --json -> downstream readonly reports
watcher -> start.sh/watchdog.sh -> tradecat watch -> cache status/probe
```

The project has no multi-user authentication or server-side permission model in
this repository. The primary quality risks are local state integrity, stable
Agent contracts, installer behavior, network failure handling, and public data
shape drift.

## Module Matrix

| Module | Source | Primary Risk | Current Test Layer |
|---|---|---|---|
| Agent contract | `agents/`, `contracts.py`, `contracts/` | schema drift, ambiguous command risk | `test_agent_contract.py`, `agent-smoke.sh` |
| JSON payloads | CLI, request fallback, watcher scripts | real output differs from schema | `test_payload_schema_validation.py` |
| Cache/state | `cache.py`, `state.py`, `migrations.py` | corrupt manifests, non-atomic writes, bad pruning | `test_cache_tui.py`, `test_state_migrations.py` |
| Transport | `sheets.py`, `request.py` | timeout/DNS/HTTP/decode misclassification | `test_transport.py` |
| Dataset semantics | `dataset_consumption_contract.json` | Agent misreads columns, time, missing values | `test_dataset_consumption_contract.py` |
| Analysis facts | `analysis.py`, `features.py` | invented symbols, trading advice leakage | `test_analysis_report.py`, `test_feature_bundle.py` |
| CLI boundaries | `cli.py` | invalid args silently accepted | `test_cli_boundaries.py`, `test_exit_codes.py` |
| TUI/plain rendering | `tui.py`, `view_model.py` | broken terminal output, link mistakes | `test_cache_tui.py` |
| Install/release | installers, CI | stable tag drift, first-run cache failure | CI installer/published smoke |

## Risk Register

| ID | Risk | Severity | Gate |
|---|---|---:|---|
| R1 | JSON command returns `ok=false` with exit code 0 | P1 | `test_exit_codes.py`, `agent-smoke.sh` |
| R2 | Schema exists but real payload no longer validates | P1 | `test_payload_schema_validation.py` |
| R3 | Transport errors misclassified and mislead Agents | P1 | `test_transport.py` |
| R4 | Invalid CLI bounds create busy loops or silent no-op | P1 | `test_cli_boundaries.py` |
| R5 | Cache writes corrupt manifest without backup/rollback | P1 | `test_state_migrations.py`, `test_cache_tui.py` |
| R6 | Agent analysis invents symbols from free text | P1 | `test_analysis_report.py`, `test_feature_bundle.py` |
| R7 | Watcher status confuses spawned process with remote health | P2 | `test_payload_schema_validation.py` |
| R8 | Public Google Sheets shape changes | P2 | `validate_data_contract.py --remote` in CI |
| R9 | Installer default stable ref lags package metadata | P2 | `test_cache_tui.py`, published smoke |
| R10 | Secrets or runtime files enter Git | P1 | `security-scan.sh`, root boundary guard |

## Test Types

| Type | Scope | Command |
|---|---|---|
| Unit | Pure helpers, parsers, state, schema utilities | `cd scripts/project && PYTHONPATH=src pytest -q tests/test_transport.py tests/test_state_migrations.py` |
| Contract | Manifest/schema/payload compatibility | `cd scripts/project && PYTHONPATH=src pytest -q tests/test_agent_contract.py tests/test_payload_schema_validation.py` |
| CLI | Exit codes, invalid input, JSON errors | `cd scripts/project && PYTHONPATH=src pytest -q tests/test_exit_codes.py tests/test_cli_boundaries.py` |
| Integration | Cache writes, TUI fallback, watcher scripts | `cd scripts/project && PYTHONPATH=src pytest -q tests/test_cache_tui.py` |
| Agent smoke | Minimal Agent fast path and failure semantics | `bash scripts/agent-smoke.sh` |
| Full local gate | Lint, tests, contracts, cleanup | `bash scripts/verify.sh` |
| Security | Secret scan and dependency audit | `bash scripts/security-scan.sh && bash scripts/supply-chain-audit.sh` |

## Release Gate

Release quality is acceptable only when all checks pass:

```bash
bash scripts/bootstrap-dev.sh
bash scripts/agent-smoke.sh
bash scripts/verify.sh
bash scripts/security-scan.sh
bash scripts/supply-chain-audit.sh
git diff --check
```

Blocking criteria:

- Any P1 risk test fails.
- Any advertised JSON schema or real payload validation fails.
- Any non-interactive failure command loses its non-zero exit code.
- Secret scan or supply-chain audit reports an unresolved finding.
- Published install smoke cannot warm the default `event_stream` cache.

## Regression Checklist

- Agent fast path: `manifest -> status -> datasets -> path -> request/sync`.
- Empty-cache behavior: `doctor`, `analyze`, `features`, `tui --plain`.
- Network failure behavior: timeout, DNS/connect, HTTP retryable/non-retryable,
  decode failure.
- Local state behavior: corrupt settings/manifest, migration rollback, gzip
  snapshots, prune dry-run/apply.
- Readonly analysis boundary: no network fetch, no symbol inference from free
  text, no score/strategy/trading advice fields.
- Watcher control plane: `status/start/stop/watchdog --json` validates against
  `tradecat.watch_status.v1`.

## Defect Template

| Field | Value |
|---|---|
| Title | Short user-visible failure |
| Module | CLI/cache/transport/contract/installer/TUI |
| Severity | P0/P1/P2/P3 |
| Environment | OS, Python, command, cache dir, ref |
| Steps | Exact command or input fixture |
| Actual | Observed output, exit code, log excerpt |
| Expected | Contracted behavior |
| Initial Cause | Product bug / test bug / environment / data drift |
| Regression | Tests or smoke checks to rerun |

