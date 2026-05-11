# Architecture

`tradecat-public` is a multi-Agent skill wrapper around a bundled user-side TradeCat project.

The Skill root is not the Python project root. It exists to hold Skill metadata,
Git metadata, references, and thin entry scripts.

```text
tradecat-public/
|-- README.md
|-- AGENTS.md                 # tracked root governance contract
|-- .git/                     # Git metadata, hidden, never moved
|-- .github/workflows/ci.yml  # CI metadata, hidden, never moved
|-- .gitignore
|-- .pre-commit-config.yaml
|-- lessons.md
|-- SKILL.md
|-- agents/
|   |-- manifest.json
|   |-- hermes.yaml
|   `-- openai.yaml
|-- references/
|   |-- index.md
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
|   |-- install-uninstall.md
|   |-- linear-flows.md
|   |-- quality-gate.md
|   |-- release.md
|   |-- stability-hardening-task-tree.md
|   |-- stability-hardening-task-tree.json
|   `-- tui-contract.md
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
```

The project itself lives in `scripts/project/` and keeps its original Python package shape:

```text
scripts/project/
|-- AGENTS.md
|-- DEBUG.md
|-- DEBUG.archive.md
|-- pyproject.toml
|-- constraints.txt
|-- contracts/
|-- scripts/
|-- src/tradecat_terminal/
`-- tests/
```

## Mission

TradeCat public reads public Google Sheets CSV endpoints, writes local JSON snapshot cache files, and exposes CLI/TUI/export flows for users and agents. `agents/manifest.json` is the canonical machine contract for Agent/Hermes consumption.

## Forbidden Paths

- No TradeCat server PostgreSQL access.
- No SQLite or SQL query layer.
- No server production-chain dependency.
- No private credentials or generated cache files in Git.
- No root `assets/` or `assets/examples/`.

## Movement Rules

- Keep `.git/`, `.github/`, `.gitignore`, `SKILL.md`, `agents/`, `references/`, and root thin validation/helper scripts in the Skill root.
- Keep Python project files, installers, project README, project scripts, `src/`, and `tests/` in `scripts/project/`.
- Keep root/project `AGENTS.md` and project `DEBUG*.md` tracked as public governance and debugging memory.
- Never put credentials, generated cache data, private `.env` values, or machine-local runtime state into tracked governance/debug files.
- When the layout changes, update `README.md`, `SKILL.md`, `references/index.md`, this file, `references/linear-flows.md` when flow behavior changes, and the tracked `AGENTS.md` copies.

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
- `cache.py`: local snapshot cache, manifest, stream event merge, prune.
- `structured_cache.py`: structured latest projections.
- `view_model.py`: display/raw/physical column model.
- `tui.py`: cache-first terminal browser and background probes.
- `scripts/project/scripts/request.py`: zero-install standard-library public request entry.
- `contracts.py`: CLI JSON schema/version and stable error object helpers.
- `scripts/bootstrap-dev.sh`: root developer bootstrap wrapper for `scripts/project/.venv`.
- `scripts/agent-smoke.sh`: root Agent readiness smoke gate for manifest, JSON schema, and exit code contracts.
- `scripts/security-scan.sh`: root secret-scan wrapper; scans tracked files by default and commit ranges in CI.
- `scripts/supply-chain-audit.sh`: root pip-audit wrapper for Python dependency vulnerability checks.
- `scripts/install-security-tools.sh`: optional local Gitleaks installer for machines without Docker.
- `scripts/clean-local-runtime.sh`: local cleanup helper for ignored runtime directories.

## Documentation Map

- `README.md`: root boundary map for the Skill wrapper, Git metadata, and bundled project location.
- `AGENTS.md`: tracked root operating contract for directory governance and movement rules.
- `lessons.md`: tracked accident lessons and prevention rules.
- `SKILL.md`: skill activation, root-level operating commands, and high-level boundaries.
- `agents/manifest.json`: canonical machine-readable Agent contract.
- `references/agent-contract.md`: Agent fast path, risk classes, exit codes, JSON schemas, and remote fetch contract.
- `references/analysis-contract.md`: readonly analysis report contract and boundary against strategy, backtest, advice, or execution semantics.
- `references/feature-contract.md`: readonly per-symbol fact bundle contract and boundary against signal, score, strategy, or execution semantics.
- `references/agent-contract-maturity-task-tree.md`: post-signoff schema, manifest, and smoke hardening tree.
- `references/agent-contract-maturity-task-tree.json`: machine-readable Agent contract maturity task tree spec.
- `references/dataset-consumption-contract.md`: dataset field semantics,
  missing-value policy, time grain, and quality-tier contract.
- `references/*.md`: long-form skill references loaded on demand.
- `references/first-run-cache.md`: first-run empty cache, cold-start diagnosis, and weak-network recovery.
- `references/linear-flows.md`: public linear flow map for cache, TUI, request, install, uninstall, export/config, and doctor diagnostics.
- `references/quality-gate.md`: validation, root audit, and release evidence checklist.
- `references/release.md`: public release notes, fixed-ref install commands, CI evidence, and rollback.
- `references/stability-hardening-task-tree.md`: current robustness hardening backlog, execution waves, and validation gates.
- `references/stability-hardening-task-tree.json`: machine-readable TP-XX hardening task tree spec.
- `references/agent-readiness-remediation-task-tree.md`: Agent/Hermes readiness remediation backlog, execution waves, and validation gates.
- `references/agent-readiness-remediation-task-tree.json`: machine-readable Agent readiness task tree spec.
- `scripts/project/README.md`: user-facing install, run, request, config, and development instructions.
- `scripts/project/AGENTS.md`: tracked project engineering contract and linear flows.
- `scripts/project/DEBUG.md`: tracked current truth and recent debugging notes.
- `scripts/project/DEBUG.archive.md`: tracked historical accident record.

Root/project `AGENTS.md` and project `DEBUG*.md` are intentionally tracked. Keep them concise, public-safe, and aligned with `README.md`, `SKILL.md`, and `references/`.
