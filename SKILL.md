---
name: tradecat-public
description: "TradeCat public Hermes skill: when installed as ~/.hermes/skills/tradecat-public, lets the user's local Hermes consume TradeCat public cache/CLI contracts, Agent market context schemas, and safe public-readonly paper/watch entrypoints without credentials or real orders."
---

# tradecat-public Skill

Use this skill when the user wants their local Hermes/Agent to understand and operate TradeCat through this installed `tradecat-public` skill. The repo root is the Hermes skill boundary; `scripts/project/` is only the bundled local tool/contract implementation used by the skill.

Current development happens in `/home/lenovo/.projects/cat/tradecat-public`. Local Hermes use should install a verified copy, clone, or symlink at `~/.hermes/skills/tradecat-public`; when it is a symlink to the development checkout, treat it as a live development install and validate before use.

## When to Use This Skill

Trigger when any of these applies:
- The user asks to run, install, debug, validate, or modify TradeCat public terminal behavior.
- The task mentions TradeCat cache, dataset registry, Google Sheets CSV, `event_stream`, CLI/TUI, installer, uninstall, one-shot request script, Binance public market context, replay report, audit journal, production paper health/daily report, or `tradecat auto context-audit/run-context`.
- The task needs the project contracts for cache-first TUI, local JSON snapshots, structured `latest.*` files, or zero-install public requests.
- The task asks to reorganize, audit, or optimize the Skill wrapper, root files, references, `AGENTS.md`, or the `scripts/project/` project boundary.

## Not For / Boundaries

- Do not connect to or write TradeCat server PostgreSQL.
- Do not add server database repair/vacuum, raw SQL query layers, or server production-chain coupling. The only allowed SQLite use in this public skill is the local paper/watch audit journal under ignored `.runtime/` paths, with schema/versioned JSON summaries and no credentials or exchange side effects.
- Do not commit credentials, Google keys, Binance keys/secrets, private `.env` files, generated cache files, `.runtime/` paper ledgers/archives/audit journals/logs, or local runtime files.
- Keep `tradecat auto` public-readonly + paper/watch unless a later explicit implementation adds deterministic testnet/mainnet gates; never let an Agent call raw order endpoints freely.
- Keep the skill root clean: project source and project docs live in `scripts/project/`; long-form skill references live in `references/`.
- Do not add root `assets/` or `assets/examples/`; project examples, if ever needed, belong under `scripts/project/` and must be documented.

## Quick Reference

### Project Location

```bash
cd /home/lenovo/.projects/cat/tradecat-public
```

### Hermes Development Mount

```bash
mkdir -p ~/.hermes/skills
ln -sfn /home/lenovo/.projects/cat/tradecat-public ~/.hermes/skills/tradecat-public
hermes -s tradecat-public
```

### Agent Fast Path

```bash
python3 -m json.tool agents/manifest.json >/dev/null
bash scripts/run-tradecat.sh status --json
bash scripts/run-tradecat.sh datasets --json
bash scripts/run-tradecat.sh path event_stream --json
bash scripts/run-tradecat.sh analyze --json
bash scripts/run-tradecat.sh features --json
```

### Agent-supplied Market Context

```bash
bash scripts/run-tradecat.sh auto context-audit --input /path/to/agent-market-context.json --json
bash scripts/run-tradecat.sh auto run-context --input /path/to/agent-market-context.json --mode paper --agent-margin-usdt <agent_margin_usdt> --paper-leverage <agent_leverage> --json
bash scripts/run-tradecat.sh auto replay-report --archive-path .runtime/cycles.jsonl --ledger-path .runtime/paper_ledger.json --json
bash scripts/run-tradecat.sh auto audit-journal --json
bash scripts/run-tradecat.sh auto health-report --json
bash scripts/run-tradecat.sh auto daily-report --json
bash scripts/run-tradecat.sh auto alert-payload --kind daily --json
```

Rules: audit before run-context; allow only public/read-only GET market endpoints; reject credentials, signatures, account/order endpoints, and real execution. Runtime reports read only ignored local paper/watch state under `.runtime/`; do not commit ledgers, archives, SQLite journals, PID files, heartbeat files, or logs.

### Validate Skill And Project

```bash
bash scripts/verify.sh
```

### Validate Agent Contract

```bash
bash scripts/agent-smoke.sh
```

### Bootstrap Development Environment

```bash
bash scripts/bootstrap-dev.sh
```

### Validate Project Only

```bash
cd scripts/project
bash scripts/verify.sh
```

### Run CLI From Source

```bash
cd scripts/project
PYTHONPATH=src python3 -m tradecat_terminal --help
PYTHONPATH=src python3 -m tradecat_terminal status --json
PYTHONPATH=src python3 -m tradecat_terminal auto --help
PYTHONPATH=src python3 -m tradecat_auto.cli paper-report --json
```

### One-shot Public Request

```bash
python3 scripts/project/scripts/request.py --datasets
python3 scripts/project/scripts/request.py event_stream --format jsonl --limit 5
```

### Inspect Cache Paths

```bash
cd scripts/project
PYTHONPATH=src python3 -m tradecat_terminal path event_stream --json
```

### Audit The Root Boundary

```bash
test ! -e assets
git ls-files | sort
bash scripts/project/scripts/guard_public_local_files.sh
```

### Skill Quality Gate

```bash
bash scripts/validate-skill.sh --strict
```

### Secret Scan

```bash
bash scripts/security-scan.sh
```

### Supply-chain Audit

```bash
bash scripts/supply-chain-audit.sh
```

### Data Contract Check

```bash
cd scripts/project
PYTHONPATH=src python3 scripts/validate_data_contract.py --remote --timeout 10
```

## Project Layout

```text
tradecat-public/
|-- README.md
|-- AGENTS.md              # tracked root governance contract
|-- lessons.md             # tracked accident lessons and prevention rules
|-- .pre-commit-config.yaml
|-- SKILL.md
|-- agents/
|   |-- manifest.json
|   |-- hermes.yaml
|   `-- openai.yaml
|-- references/
|   |-- index.md
|   |-- skill-package-governance.md
|   |-- agent-contract.md
|   |-- agent-contract-maturity-task-tree.md
|   |-- agent-contract-maturity-task-tree.json
|   |-- agent-readiness-remediation-task-tree.md
|   |-- agent-readiness-remediation-task-tree.json
|   |-- architecture.md
|   |-- analysis-contract.md
|   |-- cache-contract.md
|   |-- dataset-consumption-contract.md
|   |-- feature-contract.md
|   |-- first-run-cache.md
|   |-- hermes-agent-guide.md
|   |-- linear-flows.md
|   |-- tui-contract.md
|   |-- quality-gate.md
|   |-- install-uninstall.md
|   |-- release.md
|   |-- stability-hardening-task-tree.md
|   |-- stability-hardening-task-tree.json
|   `-- test-strategy.md
`-- scripts/
    |-- verify.sh
    |-- bootstrap-dev.sh
    |-- agent-smoke.sh
    |-- security-scan.sh
    |-- supply-chain-audit.sh
    |-- install-security-tools.sh
    |-- clean-local-runtime.sh
    |-- run-tradecat.sh
    `-- project/
        |-- AGENTS.md
        |-- DEBUG.md
        |-- DEBUG.archive.md
        |-- pyproject.toml
        |-- constraints.txt
        |-- contracts/
        |-- scripts/
        |-- src/
        |   |-- tradecat_terminal/
        |   `-- tradecat_auto/
        `-- tests/
```

## References

- `references/index.md`: navigation.
- `references/skill-package-governance.md`: Hermes Skill package shape, root/project boundary, Agent role profile placement, and runtime isolation rules.
- `references/architecture.md`: project purpose, forbidden paths, and data flows.
- `references/cache-contract.md`: local JSON cache and structured latest file contract.
- `references/dataset-consumption-contract.md`: dataset field semantics, missing values, time grain, and quality tier.
- `references/analysis-contract.md`: local readonly analysis report contract and no-trading-advice boundary.
- `references/feature-contract.md`: local readonly per-symbol feature fact bundle contract and no-scoring/no-strategy boundary.
- `references/test-strategy.md`: QA strategy, risk matrix, automation layers, and release test gate.
- `references/first-run-cache.md`: cold-start cache diagnosis, prevention rules, and recovery commands.
- `references/hermes-agent-guide.md`: human/Hermes operating guide for development-vs-production boundaries, skill installation, Agent-supplied market context, and safety checks.
- `references/linear-flows.md`: public flow map for cache, TUI, one-shot request, install, uninstall, export/config, doctor diagnostics, analysis report, feature bundle, and Agent fast path.
- `references/tui-contract.md`: TUI rendering, probing, and terminal compatibility rules.
- `references/install-uninstall.md`: installer, launcher, update, and uninstall constraints.
- `references/quality-gate.md`: pre-delivery checklist for Skill wrapper and bundled project changes.
- `references/release.md`: release evidence, fixed-ref install commands, known limits, and rollback.
- `references/stability-hardening-task-tree.md`: current robustness hardening backlog, execution waves, and validation gates.
- `references/stability-hardening-task-tree.json`: machine-readable TP-XX hardening task tree spec.
- `references/agent-readiness-remediation-task-tree.md`: current Agent/Hermes readiness remediation backlog, execution waves, and validation gates.
- `references/agent-readiness-remediation-task-tree.json`: machine-readable Agent readiness task tree spec.
- `references/agent-contract-maturity-task-tree.md`: post-signoff Agent contract maturity hardening tree.
- `references/agent-contract-maturity-task-tree.json`: machine-readable Agent contract maturity task tree spec.

## Examples

### Example 1: Validate The Bundled Project

- Input: "Run the TradeCat checks."
- Steps:
  1. Run `bash scripts/verify.sh` from the skill root.
  2. If lint is needed, run `cd scripts/project && ruff check src tests`.
- Expected output / acceptance: compileall and pytest pass; lint passes when dev dependencies are installed.

### Example 2: Inspect Local Cache Paths

- Input: "Show me where event_stream cache files live."
- Steps:
  1. Run `bash scripts/run-tradecat.sh path event_stream --json`.
  2. Read `latest_json`, `latest_jsonl`, `latest_csv`, and `stream_events`.
- Expected output / acceptance: paths point under `scripts/project/.tradecat/cache` unless `TRADECAT_CACHE_DIR` overrides them.

### Example 3: Modify TUI Behavior

- Input: "Change the TUI probe interval behavior."
- Steps:
  1. Read `references/tui-contract.md`.
  2. Edit `scripts/project/src/tradecat_terminal/tui.py`.
  3. Add or adjust focused tests in `scripts/project/tests/test_cache_tui.py`.
  4. Run `bash scripts/verify.sh`.
- Expected output / acceptance: cache-first startup, background probe, failure backoff, and plain fallback contracts remain intact.

### Example 4: Use Agent-supplied Market Context

- Input: "Use the Binance context file from an Agent and run a paper report."
- Steps:
  1. Read `references/hermes-agent-guide.md` and `references/agent-contract.md`.
  2. Run `bash scripts/run-tradecat.sh auto context-audit --input /path/to/agent-market-context.json --json`.
Only if audit `ok=true` and Agent sizing is explicit, run `bash scripts/run-tradecat.sh auto run-context --input /path/to/agent-market-context.json --mode paper --agent-margin-usdt <agent_margin_usdt> --paper-leverage <agent_leverage> --json`; without sizing, expect `agent_sizing_required` instead of a paper open. TradeCat does not set a default sizing cap; `--paper-margin-budget-usdt` is optional only when an operator explicitly wants an extra paper cap.
  4. For replay, run `bash scripts/run-tradecat.sh auto replay-report --archive-path .runtime/cycles.jsonl --ledger-path .runtime/paper_ledger.json --json`.
- Expected output / acceptance: input stays public/read-only, credentials/signatures/account/order endpoints are rejected, and output remains paper/watch with no real orders.

### Example 5: Optimize The Skill Wrapper

- Input: "Use auto-skill to optimize this skill and fill missing files."
- Steps:
  1. Read `SKILL.md`, `references/index.md`, and `references/quality-gate.md`.
  2. Keep root files limited to Skill/Git metadata, references, and thin scripts.
  3. Put project source, tests, installers, and project README under `scripts/project/`.
  4. Run the strict skill validator and `bash scripts/verify.sh`.
- Expected output / acceptance: `SKILL.md` remains short and actionable, references are navigable, root remains clean, and project validation passes.

## Maintenance

- Source project: `scripts/project/`
- Validation: `bash scripts/verify.sh` from the Skill root; run `bash scripts/validate-skill.sh --strict` when only the Skill gate is needed.
- Skill root should remain an operator entrypoint, not a second copy of the project.
