# Architecture

`tradecat-public` is the repository-root TradeCat public Python project with an
embedded multi-Agent Skill package under `skills/tradecat-public/`.
`tradecat-auto` has been merged into `src/tradecat_auto/`; new implementation
work must happen in the root project unless it is specifically Skill activation
metadata.

The repository root is the Python project root. The embedded Skill package
exists to hold Skill metadata, Agent profiles, references, and thin entry
scripts that jump back to root project scripts.

```text
tradecat-public/
|-- README.md
|-- AGENTS.md                 # tracked root governance contract
|-- .git/                     # Git metadata, hidden, never moved
|-- .github/workflows/ci.yml  # CI metadata, hidden, never moved
|-- .gitignore
|-- .pre-commit-config.yaml
|-- lessons.md
|-- DEBUG.md
|-- DEBUG.archive.md
|-- pyproject.toml
|-- constraints.txt
|-- install.sh / install.ps1
|-- uninstall.sh / uninstall.ps1
|-- contracts/
|-- resources/
|-- scripts/
|-- src/
|   |-- tradecat_terminal/
|   `-- tradecat_auto/
|-- tests/
|-- tasks/
`-- skills/
    `-- tradecat-public/
        |-- SKILL.md
        |-- agents/
        |   |-- manifest.json
        |   |-- hermes.yaml
        |   `-- openai.yaml
        |-- references/
        `-- scripts/
```

## Mission

TradeCat public reads public Google Sheets CSV endpoints, writes local JSON snapshot cache files, exposes CLI/TUI/export flows for users and agents, and now houses the Agent/Hermes paper/watch contract layer: Agent-supplied Binance public/read-only market context audit, deterministic signal/strategy/risk contracts, paper execution, paper ledger, replay/backtest, and local reports. Legacy public Binance probes remain operator diagnostics, not the canonical Agent market-context input surface. `skills/tradecat-public/agents/manifest.json` is the canonical machine contract for Agent/Hermes consumption.

## Forbidden Paths

- No TradeCat server PostgreSQL access.
- No raw SQL/server database query layer. The only allowed SQLite use is the local paper/watch audit journal under ignored `.runtime/` paths; read-only summary commands must not create missing journals or WAL files.
- No server production-chain dependency.
- No private credentials, generated cache files, paper ledgers, JSONL archives, or local runtime files in Git.
- No Binance signed account/trade endpoints or real order execution in the current `tradecat_auto` layer; only public-readonly + paper/watch is allowed until deterministic testnet/mainnet gates are implemented.
- No root `SKILL.md`, `agents/`, or `references/`; the Skill package owns those under `skills/tradecat-public/`.
- No root runtime/cache/private files tracked in Git.

## Movement Rules

- Keep `.git/`, `.github/`, `.gitignore`, `.pre-commit-config.yaml`, root validation/helper scripts, installers, `src/`, `tests/`, `contracts/`, and `resources/` in the repository-root Python project.
- Keep `SKILL.md`, `agents/`, `references/`, and Skill-local wrapper scripts only under `skills/tradecat-public/`.
- Keep root `AGENTS.md` and `DEBUG*.md` tracked as public governance and debugging memory.
- Never put credentials, generated cache data, private `.env` values, or machine-local runtime state into tracked governance/debug files.
- When the layout changes, update `README.md`, `AGENTS.md`, `skills/tradecat-public/SKILL.md`, `skills/tradecat-public/references/index.md`, this file, `skills/tradecat-public/references/linear-flows.md` when flow behavior changes, and matching tests/guards.

## Main Flow

```text
Public Google Sheets CSV
-> dataset_registry.json
-> sheets.py fetch/parse
-> cache.py snapshot or stream merge
-> structured_cache.py latest.json/latest.jsonl/latest.csv/manifest.json
-> cli.py, tui.py, view_model.py
```

```text
Local structured cache
-> dataset_consumption_contract.json
-> analysis.py deterministic observation builder
-> cli.py analyze --json
-> tradecat.analysis_report.v1 for Agent consumption
```

```text
tradecat.analysis_report.v1
-> features.py per-symbol fact normalizer
-> cli.py features --json
-> tradecat.feature_bundle.v1 for Agent consumption
```

```text
tradecat-public request.py event_stream/anomaly_panel
+ Agent-supplied Binance public/read-only market context
-> tradecat_auto.agent_market_context.py context-audit/run-context
-> tradecat_auto.market_enrichment.py
-> tradecat_auto.signals.py / strategies.py
-> tradecat_auto.risk.py deterministic risk gate
-> tradecat_auto.paper_broker.py / paper_ledger.py
-> tradecat_auto.cli run-context/paper-report/replay-report
```

## Source Boundaries

- `registry.py`: dataset/workbook/gid/data mode single source of truth.
- `dataset_contract.py`: loads the machine-readable dataset consumption
  semantics contract.
- `dataset_consumption_contract.json`: row semantics, field aliases, missing
  values, time grain, and quality tiers for Agent consumption.
- `analysis.py`: local-cache-only observation report builder; emits
  `tradecat.analysis_report.v1` without strategy, advice, backtest, execution,
  network fetch, or cache write semantics.
- `features.py`: local-cache-only symbol fact bundle builder; emits
  `tradecat.feature_bundle.v1` without signal score, strategy, backtest,
  execution, network fetch, or cache write semantics.
- `src/tradecat_auto/`: merged TradeCat → Binance public-readonly paper/watch lifecycle layer; emits enrichment, signal, strategy intent, risk decision, paper execution, paper ledger, and service cycle contracts without real orders or signed account calls.
- `cache.py`: local snapshot cache, manifest, stream event merge, prune.
- `structured_cache.py`: structured latest projections.
- `view_model.py`: display/raw/physical column model.
- `tui.py`: cache-first terminal browser and background probes.
- `scripts/request.py`: zero-install standard-library public request entry.
- `contracts.py`: CLI JSON schema/version and stable error object helpers.
- `scripts/bootstrap-dev.sh`: root developer bootstrap wrapper for `.venv`.
- `scripts/agent-smoke.sh`: root Agent readiness smoke gate for manifest, JSON schema, and exit code contracts.
- `scripts/security-scan.sh`: root secret-scan wrapper; scans tracked files by default and commit ranges in CI.
- `scripts/supply-chain-audit.sh`: root pip-audit wrapper for Python dependency vulnerability checks.
- `scripts/install-security-tools.sh`: optional local Gitleaks installer for machines without Docker.
- `scripts/clean-local-runtime.sh`: local cleanup helper for ignored runtime directories.

## Documentation Map

- `README.md`: root project install, run, request, config, automation, and development instructions.
- `AGENTS.md`: tracked root operating contract for directory governance and movement rules.
- `lessons.md`: tracked accident lessons and prevention rules.
- `skills/tradecat-public/SKILL.md`: skill activation, root-level operating commands, and high-level boundaries.
- `skills/tradecat-public/agents/manifest.json`: canonical machine-readable Agent contract.
- `skills/tradecat-public/references/agent-contract.md`: Agent fast path, risk classes, exit codes, JSON schemas, and remote fetch contract.
- `skills/tradecat-public/references/analysis-contract.md`: readonly analysis report contract and boundary against strategy, backtest, advice, or execution semantics.
- `skills/tradecat-public/references/feature-contract.md`: readonly per-symbol fact bundle contract and boundary against signal, score, strategy, or execution semantics.
- `skills/tradecat-public/references/test-strategy.md`: QA strategy, module risk matrix, automation layers, release test gate, and defect template.
- `skills/tradecat-public/references/agent-contract-maturity-task-tree.md`: post-signoff schema, manifest, and smoke hardening tree.
- `skills/tradecat-public/references/agent-contract-maturity-task-tree.json`: machine-readable Agent contract maturity task tree spec.
- `skills/tradecat-public/references/dataset-consumption-contract.md`: dataset field semantics,
  missing-value policy, time grain, and quality-tier contract.
- `skills/tradecat-public/references/*.md`: long-form skill references loaded on demand.
- `skills/tradecat-public/references/first-run-cache.md`: first-run empty cache, cold-start diagnosis, and weak-network recovery.
- `skills/tradecat-public/references/linear-flows.md`: public linear flow map for cache, TUI, request, install, uninstall, export/config, doctor diagnostics, and Agent paper/watch.
- `skills/tradecat-public/references/quality-gate.md`: validation, boundary audit, and release evidence checklist.
- `skills/tradecat-public/references/release.md`: public release notes, fixed-ref install commands, CI evidence, and rollback.
- `skills/tradecat-public/references/stability-hardening-task-tree.md`: historical robustness hardening backlog, execution waves, and validation gates.
- `skills/tradecat-public/references/stability-hardening-task-tree.json`: machine-readable TP-XX hardening task tree spec.
- `skills/tradecat-public/references/agent-readiness-remediation-task-tree.md`: historical Agent/Hermes readiness remediation backlog, execution waves, and validation gates.
- `skills/tradecat-public/references/agent-readiness-remediation-task-tree.json`: machine-readable Agent readiness task tree spec.
- `DEBUG.md`: tracked current truth and recent debugging notes.
- `DEBUG.archive.md`: tracked historical accident record.

Root `AGENTS.md` and `DEBUG*.md` are intentionally tracked. Keep them concise,
public-safe, and aligned with `README.md`, `skills/tradecat-public/SKILL.md`,
and `skills/tradecat-public/references/`.
